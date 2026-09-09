/** Where the suite's shared authenticated session is saved.
 *
 *  Lives in its own module because playwright.config.ts imports it, and a
 *  config that imports a file calling `test()` fails to load. */
export const STORAGE_STATE = "e2e/.auth/state.json";
