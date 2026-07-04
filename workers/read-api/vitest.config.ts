import { defineWorkersConfig } from "@cloudflare/vitest-pool-workers/config";

export default defineWorkersConfig({
  test: {
    poolOptions: {
      workers: {
        // R2's sqlite WAL files trip the isolated-storage stack popper
        // (github.com/cloudflare/workers-sdk known issue); tests use unique
        // keys / fresh fakes instead of relying on isolation.
        isolatedStorage: false,
        // Tests inject a fake repository, so only the R2 binding is needed;
        // configuring miniflare directly avoids pulling in the Hyperdrive
        // binding from wrangler.jsonc.
        miniflare: {
          compatibilityDate: "2026-06-01",
          compatibilityFlags: ["nodejs_compat"],
          r2Buckets: ["BUCKET"],
        },
      },
    },
  },
});
