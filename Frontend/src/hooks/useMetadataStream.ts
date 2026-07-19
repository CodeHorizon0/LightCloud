import { useEffect, useRef } from "react";

const RECONNECT_DELAY = 5000;

type MetadataUpdateHandler = (metadata: Record<string, unknown>) => void;

function useMetadataStream(apiBase: string, onMetadataUpdate: MetadataUpdateHandler): void {
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const stoppedRef = useRef<boolean>(false);
  const intentionalCloseRef = useRef<boolean>(false);

  useEffect(function effect() {
    stoppedRef.current = false;

    function cleanupEventSource(): void {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }

      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    }

    function scheduleReconnect(): void {
      if (stoppedRef.current) {
        return;
      }

      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }

      reconnectTimerRef.current = setTimeout(function onReconnectTimeout() {
        connect();
      }, RECONNECT_DELAY);
    }

    function connect(): void {
      if (stoppedRef.current) {
        return;
      }

      cleanupEventSource();
      intentionalCloseRef.current = false;

      const eventSource = new EventSource(`${apiBase}/metadata/stream`, {
        withCredentials: true,
      });

      eventSourceRef.current = eventSource;

      eventSource.onopen = function onOpen() {
        console.info("SSE connection established");
      };

      eventSource.addEventListener("metadata_update", function onMetadataEvent(event: MessageEvent) {
        try {
          const nextMetadata = JSON.parse(event.data) as Record<string, unknown>;
          onMetadataUpdate(nextMetadata);
        } catch (error) {
          console.error("SSE parse error:", error);
        }
      });

      eventSource.addEventListener("close_connection", function onCloseConnection() {
        intentionalCloseRef.current = true;
        console.warn("SSE connection closed by server, waiting reconnect...");
        cleanupEventSource();
        scheduleReconnect();
      });

      eventSource.onerror = function onError(event: Event) {
        if (intentionalCloseRef.current) {
          return;
        }

        console.error("SSE connection error", event);
        cleanupEventSource();
        scheduleReconnect();
      };
    }

    connect();

    return function cleanup() {
      stoppedRef.current = true;
      cleanupEventSource();
    };
  }, [apiBase, onMetadataUpdate]);
}

export default useMetadataStream;