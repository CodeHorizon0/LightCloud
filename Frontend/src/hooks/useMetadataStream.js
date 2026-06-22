import { useEffect, useRef } from "react";

const RECONNECT_DELAY = 5000;

function useMetadataStream(apiBase, onMetadataUpdate) {
  const eventSourceRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const stoppedRef = useRef(false);
  const intentionalCloseRef = useRef(false);

  useEffect(function () {
    stoppedRef.current = false;

    function cleanupEventSource() {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }

      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    }

    function scheduleReconnect() {
      if (stoppedRef.current) {
        return;
      }

      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }

      reconnectTimerRef.current = setTimeout(function () {
        connect();
      }, RECONNECT_DELAY);
    }

    function connect() {
      if (stoppedRef.current) {
        return;
      }

      cleanupEventSource();
      intentionalCloseRef.current = false;

      const eventSource = new EventSource(`${apiBase}/metadata/stream`, {
        withCredentials: true,
      });

      eventSourceRef.current = eventSource;

      eventSource.onopen = function () {
        console.info("SSE соединение установлено");
      };

      eventSource.addEventListener("metadata_update", function (event) {
        try {
          const nextMetadata = JSON.parse(event.data);
          onMetadataUpdate(nextMetadata);
        } catch (error) {
          console.error("SSE parse error:", error);
        }
      });

      eventSource.addEventListener("close_connection", function () {
        intentionalCloseRef.current = true;
        console.warn("SSE соединение закрыто сервером, переподключение через 5 секунд");
        cleanupEventSource();
        scheduleReconnect();
      });

      eventSource.onerror = function (event) {
        if (intentionalCloseRef.current) {
          return;
        }

        console.error("SSE ошибка соединения", event);
        cleanupEventSource();
        scheduleReconnect();
      };
    }

    connect();

    return function () {
      stoppedRef.current = true;
      cleanupEventSource();
    };
  }, [apiBase, onMetadataUpdate]);
}

export default useMetadataStream;