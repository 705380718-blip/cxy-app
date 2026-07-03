import { connectLambda, getStore } from "@netlify/blobs";

const STORE_NAME = "city-traffic-master-cities";

export async function handler(event) {
  const headers = {
    "content-type": "application/json; charset=utf-8",
    "access-control-allow-methods": "GET,PUT,OPTIONS",
    "access-control-allow-headers": "content-type",
  };

  if (event.httpMethod === "OPTIONS") return { statusCode: 204, headers, body: "" };

  try {
    connectLambda(event);
    const store = getStore(STORE_NAME);
    if (event.httpMethod === "GET") {
      const user = cleanUser(new URLSearchParams(event.queryStringParameters ?? {}).get("user") ?? event.queryStringParameters?.user ?? "");
      if (!user) return json(400, { error: "missing user" }, headers);
      const snapshot = await store.get(user, { type: "json" });
      if (!snapshot) return json(404, { snapshot: null }, headers);
      return json(200, { snapshot }, headers);
    }

    if (event.httpMethod === "PUT") {
      const body = JSON.parse(event.body || "{}");
      const user = cleanUser(body.user ?? "");
      if (!user) return json(400, { error: "missing user" }, headers);
      if (!isSnapshot(body.snapshot)) return json(400, { error: "invalid snapshot" }, headers);
      await store.setJSON(user, body.snapshot);
      return json(200, { ok: true }, headers);
    }

    return json(405, { error: "method not allowed" }, headers);
  } catch (error) {
    console.error("city cloud unavailable", error);
    return json(500, { error: "city cloud unavailable" }, headers);
  }
}

function json(statusCode, payload, headers) {
  return { statusCode, headers, body: JSON.stringify(payload) };
}

function cleanUser(value) {
  return String(value).trim().slice(0, 32);
}

function isSnapshot(value) {
  return (
    value &&
    value.version === 1 &&
    Array.isArray(value.slots) &&
    Array.isArray(value.deletedSlots) &&
    typeof value.updatedAt === "string"
  );
}
