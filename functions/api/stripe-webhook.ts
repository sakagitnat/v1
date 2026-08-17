// Cloudflare Pages Function — deployed at /api/stripe-webhook
// Point your Stripe webhook endpoint to this URL, listening for:
//   checkout.session.completed, customer.subscription.updated,
//   customer.subscription.deleted
//
// Requires env vars:
//   STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET
//   SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY (service role, NOT the anon key —
//   this function writes to subscriptions on behalf of any user, so RLS
//   must be bypassed here specifically)

import { verifyStripeSignature } from "../_stripeVerify";

interface Env {
  STRIPE_SECRET_KEY: string;
  STRIPE_WEBHOOK_SECRET: string;
  SUPABASE_URL: string;
  SUPABASE_SERVICE_ROLE_KEY: string;
}

async function upsertSubscription(env: Env, userId: string, patch: Record<string, unknown>) {
  await fetch(`${env.SUPABASE_URL}/rest/v1/subscriptions`, {
    method: "POST",
    headers: {
      apikey: env.SUPABASE_SERVICE_ROLE_KEY,
      Authorization: `Bearer ${env.SUPABASE_SERVICE_ROLE_KEY}`,
      "Content-Type": "application/json",
      Prefer: "resolution=merge-duplicates",
    },
    body: JSON.stringify({ user_id: userId, ...patch }),
  });
}

export const onRequestPost: PagesFunction<Env> = async (context) => {
  const { request, env } = context;
  const rawBody = await request.text();

  const verification = await verifyStripeSignature(
    rawBody,
    request.headers.get("Stripe-Signature"),
    env.STRIPE_WEBHOOK_SECRET
  );
  if (!verification.valid) {
    console.error("Stripe webhook rejected:", verification.reason);
    return Response.json({ error: `Signature verification failed: ${verification.reason}` }, { status: 400 });
  }

  const event = JSON.parse(rawBody);

  switch (event.type) {
    case "checkout.session.completed": {
      const session = event.data.object;
      const userId = session.metadata?.user_id;
      if (userId) {
        await upsertSubscription(env, userId, {
          stripe_customer_id: session.customer,
          stripe_subscription_id: session.subscription,
        });
      }
      break;
    }
    case "customer.subscription.updated":
    case "customer.subscription.deleted": {
      const sub = event.data.object;
      const periodEnd = sub.status === "active" ? new Date(sub.current_period_end * 1000).toISOString() : null;
      const lookup = await fetch(
        `${env.SUPABASE_URL}/rest/v1/subscriptions?stripe_customer_id=eq.${sub.customer}&select=user_id`,
        {
          headers: {
            apikey: env.SUPABASE_SERVICE_ROLE_KEY,
            Authorization: `Bearer ${env.SUPABASE_SERVICE_ROLE_KEY}`,
          },
        }
      );
      const rows = await lookup.json<{ user_id: string }[]>();
      if (rows[0]) {
        await upsertSubscription(env, rows[0].user_id, { stripe_period_end: periodEnd });
      }
      break;
    }
  }

  return Response.json({ received: true });
};
