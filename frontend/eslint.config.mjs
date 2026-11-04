import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

export default defineConfig([
  ...nextVitals, ...nextTypescript,
  {
    files: ["tests/**/*.ts"],
    rules: {
      "no-restricted-syntax": ["error",
        { selector: "CallExpression[callee.property.name=/^(skip|fixme|only)$/]", message: "E2E must not be skipped, focused, or marked fixme." },
        { selector: "CallExpression[callee.property.name='waitForTimeout']", message: "Use web-first assertions, polling, or Playwright Clock instead of fixed sleeps." },
      ],
    },
  },
  globalIgnores([".next/**", "next-env.d.ts"]),
]);
