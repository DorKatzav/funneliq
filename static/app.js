/* FunnelIQ browser helpers: Supabase session + authenticated API calls.
 *
 * Only the PUBLIC anon key ever reaches the browser (fetched from /api/config).
 * Every API call carries the user's access token; the server verifies it and
 * queries Supabase with it, so Row Level Security applies end to end.
 */
window.FunnelIQ = (() => {
  let _client = null;

  async function getClient() {
    if (_client) return _client;
    const res = await fetch("/api/config");
    const cfg = await res.json();
    if (!cfg.supabase_url || !cfg.supabase_anon_key) {
      throw new Error("Supabase is not configured on the server");
    }
    _client = window.supabase.createClient(cfg.supabase_url, cfg.supabase_anon_key);
    return _client;
  }

  async function getSession() {
    const client = await getClient();
    const { data } = await client.auth.getSession();
    return data.session || null;
  }

  /** Redirect to the login page unless a session exists. Returns the session. */
  async function requireSession() {
    const session = await getSession();
    if (!session) {
      window.location.replace("/static/login.html");
      return null;
    }
    return session;
  }

  async function signIn(email, password) {
    const client = await getClient();
    const { data, error } = await client.auth.signInWithPassword({ email, password });
    if (error) throw error;
    return data.session;
  }

  async function signOut() {
    const client = await getClient();
    await client.auth.signOut();
    window.location.replace("/static/login.html");
  }

  /** fetch() wrapper that adds the bearer token and parses JSON (throws on non-2xx). */
  async function api(path, options = {}) {
    const session = await requireSession();
    if (!session) throw new Error("no session");
    const headers = Object.assign(
      { Authorization: `Bearer ${session.access_token}`, Accept: "application/json" },
      options.body ? { "Content-Type": "application/json" } : {},
      options.headers || {}
    );
    const res = await fetch(path, { ...options, headers });
    if (res.status === 401) {
      await signOut();
      throw new Error("session expired");
    }
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail ? JSON.stringify(body.detail) : `HTTP ${res.status}`);
    return body;
  }

  const fmt = {
    int: (n) => (n == null ? "—" : Number(n).toLocaleString("en-US")),
    money: (n) => (n == null ? "—" : "₪" + Number(n).toLocaleString("en-US", { maximumFractionDigits: 0 })),
    pct: (x) => (x == null ? "—" : (100 * x).toFixed(1) + "%"),
  };

  return { getClient, getSession, requireSession, signIn, signOut, api, fmt };
})();
