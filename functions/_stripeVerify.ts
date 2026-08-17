// Manual Stripe webhook signature verification using the Web Crypto API.
// Cloudflare Workers/Pages Functions don't have Node's `crypto` module or
// the Stripe SDK's built-in verifier, so this reimplements Stripe's documented
// scheme: https://stripe.com/docs/webhooks/signatures
//
// Stripe-Signature header format: "t=<timestamp>,v1=<hex_signature>[,v0=...]"
// Expected signature = HMAC-SHA256(webhookSecret, `${timestamp}.${rawBody}`)

const TOLERANCE_SECONDS = 300; // reject events older than 5 minutes (replay protection)

export async function verifyStripeSignature(
  rawBody: string,
  signatureHeader: string | null,
  webhookSecret: string
): Promise<{ valid: boolean; reason?: string }> {
  if (!signatureHeader) return { valid: false, reason: "missing Stripe-Signature header" };

  const parts = Object.fromEntries(
    signatureHeader.split(",").map((kv) => {
      const [k, v] = kv.split("=");
      return [k, v];
    })
  );
  const timestamp = parts["t"];
  const v1Signature = parts["v1"];
  if (!timestamp || !v1Signature) return { valid: false, reason: "malformed signature header" };

  const age = Math.abs(Date.now() / 1000 - Number(timestamp));
  if (age > TOLERANCE_SECONDS) return { valid: false, reason: "timestamp outside tolerance (possible replay)" };

  const signedPayload = `${timestamp}.${rawBody}`;

  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(webhookSecret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const signatureBytes = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(signedPayload));
  const expectedHex = Array.from(new Uint8Array(signatureBytes))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");

  // Constant-time comparison to avoid timing attacks.
  if (expectedHex.length !== v1Signature.length) return { valid: false, reason: "signature mismatch" };
  let diff = 0;
  for (let i = 0; i < expectedHex.length; i++) {
    diff |= expectedHex.charCodeAt(i) ^ v1Signature.charCodeAt(i);
  }
  if (diff !== 0) return { valid: false, reason: "signature mismatch" };

  return { valid: true };
}
