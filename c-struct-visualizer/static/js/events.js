/**
 * EventBus — Simple pub/sub system for inter-module communication.
 * All module communication flows through this bus.
 */

const listeners = {};

export const EventBus = {
  /**
   * Subscribe to an event.
   * @param {string} event - Event name
   * @param {Function} callback - Handler function
   */
  on(event, callback) {
    if (!listeners[event]) {
      listeners[event] = [];
    }
    listeners[event].push(callback);
  },

  /**
   * Unsubscribe from an event.
   * @param {string} event - Event name
   * @param {Function} callback - Handler to remove
   */
  off(event, callback) {
    if (!listeners[event]) return;
    listeners[event] = listeners[event].filter((cb) => cb !== callback);
  },

  /**
   * Emit an event with optional data.
   * @param {string} event - Event name
   * @param {*} data - Payload
   */
  emit(event, data) {
    if (!listeners[event]) return;
    for (const callback of listeners[event]) {
      callback(data);
    }
  },
};

/* Supported events:
 * tableAdded, tableRemoved, tableMoved, tableDragging,
 * filterChanged, layoutChanged,
 * connectionAdded, connectionRemoved,
 * viewportChanged, stateReset,
 * blockCollapsed, blockExpanded,
 * searchStarted, searchResultsReady, searchCleared,
 * traceStarted, traceResultsReady,
 * panToTable, stateChanged
 */
