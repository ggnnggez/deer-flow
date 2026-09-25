import "./styles.css";

import { createElement } from "react";
import { createRoot } from "react-dom/client";

import { backendBaseFromModuleUrl } from "./api";
import { ResidencyApp } from "./app";

/**
 * The plugin module the host loads (`assets-v1`). One page surface, mounted
 * into the host's Shadow DOM with this bundle's own React and stylesheet, and
 * one conversation action that opens the page for the current conversation.
 */

const NAMESPACE = "community.context-residency";
const SURFACE_ID = "board";

function readSearch(): { threadId: string | null; taskId: string | null; stepSeq: number | null } {
  const params = new URLSearchParams(window.location.search);
  const step = params.get("step");
  const stepSeq = step !== null && /^\d+$/.test(step) ? Number(step) : null;
  return { threadId: params.get("thread"), taskId: params.get("task"), stepSeq };
}

interface SurfaceContext {
  locale: string;
  threadId?: string;
  signal: AbortSignal;
}

/**
 * The compiled stylesheet Vite emits next to this module. Built from a
 * non-literal name on purpose: a literal ``new URL("./styles.css",
 * import.meta.url)`` would make Vite resolve the *source* file at build time
 * and inline it as a data URL, and the compiled sheet would never load.
 */
function stylesheetUrl(): string {
  const name = ["styles", "css"].join(".");
  return new URL(name, import.meta.url).href;
}

function mountBoard(root: HTMLElement, context: SurfaceContext) {
  const stylesheet = document.createElement("link");
  stylesheet.rel = "stylesheet";
  stylesheet.crossOrigin = "use-credentials";
  stylesheet.href = stylesheetUrl();
  const container = document.createElement("div");
  root.append(stylesheet, container);

  const search = readSearch();
  const reactRoot = createRoot(container);
  reactRoot.render(
    createElement(ResidencyApp, {
      base: backendBaseFromModuleUrl(import.meta.url),
      locale: context.locale,
      signal: context.signal,
      initialThreadId: search.threadId ?? context.threadId ?? null,
      initialTaskId: search.taskId,
      initialStepSeq: search.stepSeq,
    }),
  );
  return {
    dispose() {
      reactRoot.unmount();
      stylesheet.remove();
      container.remove();
    },
  };
}

export default {
  apiVersion: 1 as const,
  module: "context-residency.v1",
  icon: "layers",
  surfaces: [
    {
      id: SURFACE_ID,
      slot: "page" as const,
      title: "Context residency",
      navigation: { label: "Context residency", labelZh: "上下文留存", icon: "layers" },
      mount: mountBoard,
    },
  ],
  conversationActions(_t: unknown, locale = "en") {
    const zh = locale.startsWith("zh");
    return {
      label: zh ? "上下文留存" : "Context residency",
      icon: "layers",
      actions: [
        {
          id: "open-residency",
          label: zh ? "查看这个会话的上下文留存" : "Open context residency for this conversation",
          icon: "layers",
          available: (settings: { enabled?: unknown }) => settings.enabled === true,
          async execute(context: { thread: { thread_id: string } }) {
            const url = new URL(`/workspace/extensions/${encodeURIComponent(NAMESPACE)}/${SURFACE_ID}`, window.location.origin);
            url.searchParams.set("thread", context.thread.thread_id);
            window.location.assign(url.toString());
          },
        },
      ],
    };
  },
};
