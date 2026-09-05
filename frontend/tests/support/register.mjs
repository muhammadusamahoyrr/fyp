/* Registers the JSX + alias loader for `node --test`. Used via `--import`. */
import { register } from "node:module";
import { pathToFileURL } from "node:url";

register("./jsx-loader.mjs", pathToFileURL(import.meta.filename));
