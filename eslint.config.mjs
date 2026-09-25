/**
 * ESLint flat config.
 *
 * `eslint-config-next@16` ships native flat configs, so it is imported directly.
 * The scaffold wires it through `FlatCompat`, which is for eslintrc-format
 * configs and fails here with a circular-reference error while normalising the
 * plugin graph. Importing the arrays is both correct and simpler.
 */

import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

const config = [
  {
    ignores: [
      "node_modules/**",
      ".next/**",
      "out/**",
      "build/**",
      "next-env.d.ts",
      "public/pdf.worker.min.mjs",
    ],
  },
  ...nextCoreWebVitals,
  ...nextTypescript,
  {
    rules: {
      // Unused variables are a real signal, but a deliberately ignored argument
      // should be expressible rather than worked around.
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_", caughtErrors: "none" },
      ],
      // This codebase renders untrusted model output and document text. Any use of
      // dangerouslySetInnerHTML would need a deliberate, reviewed exemption.
      "react/no-danger": "error",
    },
  },
];

export default config;
