import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles/global.css";
import "./styles/dark.css";

const root = document.getElementById("root");
if (!root) throw new Error("找不到 #root 挂载节点。");

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
