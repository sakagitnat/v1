// Cloudflare Pages Function — deployed automatically at /api/create-checkout-session
// Requires env vars set in Cloudflare Pages dashboard (Settings > Environment variables):
//   STRIPE_SECRET_KEY
//   STRIPE_PRICE_MONTHLY   (Stripe Price ID for the monthly plan)
//   STRIPE_PRICE_YEARLY    (Stripe Price ID for the yearly plan)
//   PUBLIC_SITE_URL        (e.g. https://grove.pages.dev)

interface Env {
  STRIPE_SECRET_KEY: string;
  STRIPE_PRICE_MONTHLY: string;
  STRIPE_PRICE_YEARLY: string;
  PUBLIC_SITE_URL: string;
}

export const onRequestPost: PagesFunction<Env> = async (context) => {
  const { request, env } = context;
  const { planId, userId, email } = await request.json<{
    planId: string;
    userId: string;
    email: string;
  }>();

  const priceId = planId === "yearly" ? env.STRIPE_PRICE_YEARLY : env.STRIPE_PRICE_MONTHLY;
  if (!priceId) {
    return Response.json({ error: "Price ID not configured" }, { status: 500 });
  }

  const body = new URLSearchParams({
    mode: "subscription",
    "line_items[0][price]": priceId,
    "line_items[0][quantity]": "1",
    success_url: `${env.PUBLIC_SITE_URL}/profile?checkout=success`,
    cancel_url: `${env.PUBLIC_SITE_URL}/pro?checkout=cancelled`,
    customer_email: email,
    "metadata[user_id]": userId,
  });

  const res = await fetch("https://api.stripe.com/v1/checkout/sessions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.STRIPE_SECRET_KEY}`,
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body,
  });

  const session = await res.json<{ url?: string; error?: { message: string } }>();
  if (session.error) {
    return Response.json({ error: session.error.message }, { status: 400 });
  }
  return Response.json({ url: session.url });
};
