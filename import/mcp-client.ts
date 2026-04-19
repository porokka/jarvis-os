/**
 * MCP Client for interfacing with the Jarvis OS MCP server
 * This client allows communication with the MCP server to execute tools
 * and access file system, git, and other operations
 */

interface ToolCall {
  name: string;
  arguments: Record<string, any>;
}

interface ToolResult {
  toolName: string;
  result: any;
  error?: string;
}

class MCPClient {
  private baseUrl: string;
  private token: string | null;

  constructor(baseUrl: string, token: string | null = null) {
    this.baseUrl = baseUrl;
    this.token = token;
  }

  /**
   * Execute a tool call through the MCP server
   */
  async executeTool(toolCall: ToolCall): Promise<ToolResult> {
    try {
      const response = await fetch(`${this.baseUrl}/api/tools/execute`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(this.token && { 'Authorization': `Bearer ${this.token}` })
        },
        body: JSON.stringify({
          toolName: toolCall.name,
          arguments: toolCall.arguments
        })
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const result = await response.json();
      return {
        toolName: toolCall.name,
        result: result.data
      };
    } catch (error) {
      return {
        toolName: toolCall.name,
        result: null,
        error: error instanceof Error ? error.message : 'Unknown error'
      };
    }
  }

  /**
   * Get list of available tools
   */
  async getAvailableTools(): Promise<any[]> {
    try {
      const response = await fetch(`${this.baseUrl}/api/tools/list`, {
        headers: {
          ...(this.token && { 'Authorization': `Bearer ${this.token}` })
        }
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const result = await response.json();
      return result.tools || [];
    } catch (error) {
      console.error('Error fetching tools:', error);
      return [];
    }
  }

  /**
   * Read a file using the vault skill
   */
  async readFile(filePath: string): Promise<string> {
    try {
      const toolCall: ToolCall = {
        name: 'read_vault_file',
        arguments: { path: filePath }
      };

      const result = await this.executeTool(toolCall);

      if (result.error) {
        throw new Error(result.error);
      }

      return result.result.content || '';
    } catch (error) {
      throw new Error(`Failed to read file ${filePath}: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
  }

  /**
   * Write content to a file using the vault skill
   */
  async writeFile(filePath: string, content: string): Promise<void> {
    try {
      const toolCall: ToolCall = {
        name: 'write_vault_file',
        arguments: {
          path: filePath,
          content: content
        }
      };

      const result = await this.executeTool(toolCall);

      if (result.error) {
        throw new Error(result.error);
      }
    } catch (error) {
      throw new Error(`Failed to write file ${filePath}: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
  }

  /**
   * Execute shell command
   */
  async executeShellCommand(command: string): Promise<string> {
    try {
      const toolCall: ToolCall = {
        name: 'shell_command',
        arguments: { command: command }
      };

      const result = await this.executeTool(toolCall);

      if (result.error) {
        throw new Error(result.error);
      }

      return result.result.output || '';
    } catch (error) {
      throw new Error(`Failed to execute command "${command}": ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
  }

  /**
   * Perform git operations
   */
  async gitOperation(operation: string, args: Record<string, any>): Promise<any> {
    try {
      const toolCall: ToolCall = {
        name: 'git_operation',
        arguments: {
          operation: operation,
          ...args
        }
      };

      const result = await this.executeTool(toolCall);

      if (result.error) {
        throw new Error(result.error);
      }

      return result.result;
    } catch (error) {
      throw new Error(`Git operation "${operation}" failed: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
  }
}

export { MCPClient, ToolCall, ToolResult };