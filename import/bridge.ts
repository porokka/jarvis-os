/**
 * Bridge system for communication between Jarvis OS components
 * This handles communication between the coding interface and other systems
 */

interface BridgeMessage {
  type: string;
  payload: any;
  timestamp: Date;
}

interface BridgeListener {
  id: string;
  callback: (message: BridgeMessage) => void;
}

class Bridge {
  private listeners: BridgeListener[] = [];
  private isInitialized = false;

  constructor() {
    this.init();
  }

  private init() {
    if (this.isInitialized) return;

    // Initialize bridge connection
    console.log('Bridge system initialized');
    this.isInitialized = true;
  }

  /**
   * Subscribe to a message type
   */
  subscribe(type: string, callback: (message: BridgeMessage) => void): string {
    const id = `listener_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    this.listeners.push({ id, callback });
    console.log(`Subscribed to message type: ${type} with ID: ${id}`);
    return id;
  }

  /**
   * Unsubscribe from a message type
   */
  unsubscribe(id: string): void {
    this.listeners = this.listeners.filter(listener => listener.id !== id);
    console.log(`Unsubscribed listener with ID: ${id}`);
  }

  /**
   * Send a message through the bridge
   */
  sendMessage(type: string, payload: any): void {
    const message: BridgeMessage = {
      type,
      payload,
      timestamp: new Date()
    };

    // Notify all listeners
    this.listeners.forEach(listener => {
      try {
        listener.callback(message);
      } catch (error) {
        console.error(`Error in bridge listener ${listener.id}:`, error);
      }
    });

    console.log(`Sent message of type: ${type}`);
  }

  /**
   * Send a message to the MCP server
   */
  async sendToMCP(toolCall: any): Promise<any> {
    // This would connect to the actual MCP server
    // For now, we'll simulate the response
    console.log('Sending tool call to MCP:', toolCall);

    // Simulate MCP response
    return new Promise((resolve) => {
      setTimeout(() => {
        resolve({
          success: true,
          data: `Simulated response to ${toolCall.name}`,
          timestamp: new Date()
        });
      }, 500);
    });
  }

  /**
   * Get system status
   */
  getStatus(): any {
    return {
      isInitialized: this.isInitialized,
      listenerCount: this.listeners.length,
      timestamp: new Date()
    };
  }
}

// Create a singleton instance
const bridge = new Bridge();

export { Bridge, bridge, BridgeMessage };