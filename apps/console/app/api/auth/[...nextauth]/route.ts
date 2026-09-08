import NextAuth, { type NextAuthOptions } from "next-auth";
import KeycloakProvider from "next-auth/providers/keycloak";

// Browser reaches Keycloak at localhost:8180; this server reaches it at
// keycloak:8080 - one discovered "issuer" can't serve both, so every
// endpoint is set explicitly instead of using OIDC discovery.
const PUBLIC_BASE = `${process.env.KEYCLOAK_PUBLIC_URL}/realms/verisettle`;
const INTERNAL_BASE = `${process.env.KEYCLOAK_INTERNAL_URL}/realms/verisettle`;

export const authOptions: NextAuthOptions = {
  providers: [
    KeycloakProvider({
      clientId: process.env.KEYCLOAK_CLIENT_ID!,
      clientSecret: process.env.KEYCLOAK_CLIENT_SECRET!,
      wellKnown: undefined,
      issuer: PUBLIC_BASE,
      // "roles" isn't in next-auth's default scope, but realm_access.roles
      // needs it requested to land in the id_token.
      authorization: {
        url: `${PUBLIC_BASE}/protocol/openid-connect/auth`,
        params: { scope: "openid email profile roles" },
      },
      token: `${INTERNAL_BASE}/protocol/openid-connect/token`,
      userinfo: `${INTERNAL_BASE}/protocol/openid-connect/userinfo`,
      jwks_endpoint: `${INTERNAL_BASE}/protocol/openid-connect/certs`,
      checks: ["state"],
    }),
  ],
  callbacks: {
    async jwt({ token, account }) {
      // Keycloak's userinfo response has no realm_access.roles - only the
      // id_token does, and next-auth already verified it during the code
      // exchange, so decoding it here needs no re-verification.
      if (account?.id_token) {
        const payload = JSON.parse(Buffer.from(account.id_token.split(".")[1], "base64").toString());
        const roles = (payload.realm_access?.roles as string[] | undefined) ?? [];
        token.roles = roles.filter((r) => ["ap-clerk", "controller", "cfo-approver"].includes(r));
      }
      return token;
    },
    async session({ session, token }) {
      session.roles = (token.roles as string[]) ?? [];
      return session;
    },
  },
  session: { strategy: "jwt" },
};

const handler = NextAuth(authOptions);
export { handler as GET, handler as POST };
