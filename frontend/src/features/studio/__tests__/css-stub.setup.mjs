// Test-only setup: component modules import their stylesheet for the
// browser build; under node --test a CSS import is meaningless, so the
// CommonJS extension handler for .css is stubbed to an empty module.
import Module from "node:module";

if (Module._extensions) {
  Module._extensions[".css"] = (mod) => {
    mod.exports = {};
  };
}
