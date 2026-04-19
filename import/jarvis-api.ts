/**
 * Jarvis OS API interface
 * This provides a unified interface for interacting with the Jarvis OS
 */

import { MCPClient } from './mcp-client';
import { bridge } from './bridge';

class JarvisAPI {
  private mcpClient: MCPClient;
  private isInitialized = false;

  constructor() {
    // Initialize with default MCP server URL
    this.mcpClient = new MCPClient('http://localhost:3001');
  }

  /**
   * Initialize the Jarvis API
   */
  async initialize(): Promise<void> {
    if (this.isInitialized) return;

    console.log('Initializing Jarvis API...');

    // Test connection to MCP server
    try {
      const tools = await this.mcpClient.getAvailableTools();
      console.log('Connected to MCP server. Available tools:', tools.length);

      this.isInitialized = true;
      console.log('Jarvis API initialized successfully');
    } catch (error) {
      console.error('Failed to initialize Jarvis API:', error);
      throw new Error('Failed to connect to MCP server');
    }
  }

  /**
   * Get the current system status
   */
  getStatus(): any {
    return {
      isInitialized: this.isInitialized,
      mcpConnected: true, // Simplified for this example
      timestamp: new Date()
    };
  }

  /**
   * Read a file from the vault
   */
  async readFile(filePath: string): Promise<string> {
    if (!this.isInitialized) {
      throw new Error('Jarvis API not initialized');
    }

    return await this.mcpClient.readFile(filePath);
  }

  /**
   * Write content to a file in the vault
   */
  async writeFile(filePath: string, content: string): Promise<void> {
    if (!this.isInitialized) {
      throw new Error('Jarvis API not initialized');
    }

    await this.mcpClient.writeFile(filePath, content);
  }

  /**
   * Execute a shell command
   */
  async executeCommand(command: string): Promise<string> {
    if (!this.isInitialized) {
      throw new Error('Jarvis API not initialized');
    }

    return await this.mcpClient.executeShellCommand(command);
  }

  /**
   * Perform git operations
   */
  async gitOperation(operation: string, args: Record<string, any>): Promise<any> {
    if (!this.isInitialized) {
      throw new Error('Jarvis API not initialized');
    }

    return await this.mcpClient.gitOperation(operation, args);
  }

  /**
   * Send a message through the bridge
   */
  sendMessage(type: string, payload: any): void {
    bridge.sendMessage(type, payload);
  }

  /**
   * Subscribe to bridge messages
   */
  subscribeToBridge(type: string, callback: (message: any) => void): string {
    return bridge.subscribe(type, callback);
  }

  /**
   * Unsubscribe from bridge messages
   */
  unsubscribeFromBridge(id: string): void {
    bridge.unsubscribe(id);
  }
}

// Create a singleton instance
const jarvisAPI = new JarvisAPI();

export { JarvisAPI, jarvisAPI };