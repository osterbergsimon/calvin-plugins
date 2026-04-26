import js from "@eslint/js";
import globals from "globals";

export default [
  {
    ignores: ["**/frontend/dist.js", "**/node_modules/**"],
  },
  js.configs.recommended,
  {
    files: ["**/*.js"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: {
        ...globals.browser,
        ...globals.node,
      },
    },
  },
];
