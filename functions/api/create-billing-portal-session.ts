interface Env {
  STRIPE_SECRET_KEY: string;
  SUPABASE_URL: string;
  SUPABASE_SERVICE_ROLE_KEY: string;
  PUBLIC_SITE_URL: string;
}

export const onRequestPost: PagesFunction<Env> = async (context) => {
  const { request, env } = context;
  const { userId } = await request.json<{ userId: string }>();

  const lookup = await fetch(
    `${env.SUPABASE_URL}/rest/v1/subscriptions?user_id=eq.${userId}&select=stripe_customer_id`,
    {
      headers: {
        apikey: env.SUPABASE_SERVICE_ROLE_KEY,
        Authorization: `Bearer ${env.SUPABASE_SERVICE_ROLE_KEY}`,
      },
    }
  );
  const rows = await lookup.json<{ stripe_customer_id: string }[]>();
  const customerId = rows[0]?.stripe_customer_id;
  if (!customerId) {
    return Response.json({ error: "No Stripe customer found for this user" }, { status: 404 });
  }

  const res = await fetch("https://api.stripe.com/v1/billing_portal/sessions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.STRIPE_SECRET_KEY}`,
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({
      customer: customerId,
      return_url: `${env.PUBLIC_SITE_URL}/profile`,
    }),
  });
  const session = await res.json<{ url?: string; error?: { message: string } }>();
  if (session.error) return Response.json({ error: session.error.message }, { status: 400 });
  return Response.json({ url: session.url });
};
