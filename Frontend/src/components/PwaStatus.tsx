import { useEffect, useState } from "react";
import styles from "./PwaStatus.module.css";

interface InstallPrompt extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

const DISMISSED_KEY = "LightCloud.pwa-recommendation-dismissed";

function recommendationDismissed(): boolean {
  try {
    return localStorage.getItem(DISMISSED_KEY) === "true";
  } catch {
    return false;
  }
}

export default function PwaStatus() {
  const [dismissed, setDismissed] = useState(recommendationDismissed);
  const [install, setInstall] = useState<InstallPrompt | null>(null);
  const [state, setState] = useState("Preparing offline app...");
  const [waiting, setWaiting] = useState(false);
  const [installing, setInstalling] = useState(false);

  useEffect(function prepareApp() {
    let active = true;
    let registration: ServiceWorkerRegistration | undefined;
    const cleanups: Array<() => void> = [];
    function onInstall(event: Event) {
      event.preventDefault();
      setInstall(event as InstallPrompt);
    }
    function installed() {
      setInstall(null);
    }
    function preferenceChanged(event: StorageEvent) {
      if (event.key === DISMISSED_KEY || event.key === null)
        setDismissed(recommendationDismissed());
    }
    window.addEventListener("storage", preferenceChanged);
    window.addEventListener("beforeinstallprompt", onInstall);
    window.addEventListener("appinstalled", installed);
    async function register() {
      if (!import.meta.env.PROD) {
        setState("Offline app is available in production builds");
        return;
      }
      if (!("serviceWorker" in navigator) || !window.isSecureContext) {
        setState("Offline app requires HTTPS or localhost");
        return;
      }
      try {
        registration = await navigator.serviceWorker.register("/sw.js", {
          scope: "/",
          updateViaCache: "none",
        });
        if (!active) return;
        function updateState() {
          if (!active || !registration) return;
          setWaiting(Boolean(registration.waiting));
          setState(
            registration.active
              ? "App ready offline"
              : "Preparing offline app...",
          );
          const worker = registration.installing;
          if (worker) {
            function changed() {
              updateStateWithoutListener();
              if (worker?.state === "redundant" && !registration?.active)
                setState(
                  "Offline app could not be saved. Retry with a connection.",
                );
            }
            worker.addEventListener("statechange", changed);
            cleanups.push(function () {
              worker.removeEventListener("statechange", changed);
            });
          }
        }
        function updateStateWithoutListener() {
          if (!active || !registration) return;
          setWaiting(Boolean(registration.waiting));
          setState(
            registration.active
              ? "App ready offline"
              : "Preparing offline app...",
          );
        }
        updateState();
        registration.addEventListener("updatefound", updateState);
        navigator.serviceWorker.addEventListener(
          "controllerchange",
          updateStateWithoutListener,
        );
        cleanups.push(function () {
          registration?.removeEventListener("updatefound", updateState);
          navigator.serviceWorker.removeEventListener(
            "controllerchange",
            updateStateWithoutListener,
          );
        });
      } catch {
        if (active)
          setState("Offline app is unavailable. Retry with a connection.");
      }
    }
    function checkUpdate() {
      if (navigator.onLine) void registration?.update().catch(function () {});
    }
    void register();
    window.addEventListener("online", checkUpdate);
    const timer = setInterval(checkUpdate, 60 * 60 * 1000);
    return function cleanup() {
      active = false;
      clearInterval(timer);
      for (const dispose of cleanups) dispose();
      window.removeEventListener("online", checkUpdate);
      window.removeEventListener("storage", preferenceChanged);
      window.removeEventListener("beforeinstallprompt", onInstall);
      window.removeEventListener("appinstalled", installed);
    };
  }, []);

  async function installApp() {
    if (!install || installing) return;
    setInstalling(true);
    try {
      await install.prompt();
      const choice = await install.userChoice;
      if (choice.outcome === "accepted")
        void navigator.storage?.persist?.().catch(function () {});
    } catch {
      setState("Use your browser menu to install the app.");
    } finally {
      setInstall(null);
      setInstalling(false);
    }
  }

  function dismissRecommendation() {
    setDismissed(true);
    try {
      localStorage.setItem(DISMISSED_KEY, "true");
    } catch {
      /* Keep it hidden for this visit. */
    }
  }

  if (dismissed) return null;

  return (
    <aside className={styles.bar} aria-label="Application status">
      <span role="status">
        {state}
        {waiting
          ? ". Update ready. Close all LightCloud windows to apply."
          : ""}
      </span>
      {install ? (
        <button type="button" onClick={installApp} disabled={installing}>
          Install app
        </button>
      ) : null}
      <button
        type="button"
        className={styles.closeButton}
        aria-label="Dismiss PWA recommendation"
        onClick={dismissRecommendation}
      >
        ×
      </button>
    </aside>
  );
}
