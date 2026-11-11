import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { tokenSheet } from "./tokens";
import "./styles.css";

const tokens = document.createElement("style");
tokens.textContent = tokenSheet;
document.head.prepend(tokens);

const root = document.getElementById("root");
if (!root) throw new Error("root missing");

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
