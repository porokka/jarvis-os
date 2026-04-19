# Jarvis OS Coding Interface

This is a coding interface implementation for the Jarvis OS project, similar to Claude Code. It provides a unified interface for code editing, chatting with AI, and executing system operations through MCP tools.

## Features

- **Integrated Code Editor**: With file explorer and syntax highlighting
- **Chat Interface**: For text and voice input to interact with Claude model
- **MCP Integration**: Access to file system, git, and other tools
- **System Logging**: Real-time display of system logs
- **Bridge Communication**: Seamless communication between components

## Components

### 1. Main Coding Interface (`CodingInterface.tsx`)
The main component that orchestrates all other components and provides the UI layout.

### 2. Code Editor (`CodeEditor.tsx`)
A file explorer and code editor with:
- File tree navigation
- Code editing capabilities
- File selection and content display

### 3. Chat Interface (`ChatInterface.tsx`)
A chat interface with:
- Text input
- Voice input simulation
- Message history display
- Typing indicators

### 4. Logs Display (`LogsDisplay.tsx`)
Displays system logs at the top of the interface.

### 5. MCP Client (`mcp-client.ts`)
Handles communication with the MCP server to execute tools and access system operations.

### 6. Bridge System (`bridge.ts`)
Manages communication between different components of the Jarvis OS.

### 7. Jarvis API (`jarvis-api.ts`)
Unified API interface for interacting with the Jarvis OS.

## Usage

1. **Initialize the interface**:
   ```tsx
   import CodingInterface from './components/CodingInterface';
   
   function App() {
     return (
       <div className="app">
         <CodingInterface />
       </div>
     );
   }
   ```

2. **Open via UI button or voice command**:
   - The interface can be opened via a UI button
   - Voice command "open coding" should trigger the interface

3. **Use the different panels**:
   - **Logs panel**: Shows system logs at the top
   - **Code editor**: Edit files and navigate the file system
   - **Chat interface**: Communicate with Claude model and execute commands

## Integration Points

- **MCP Server**: Access to file system, git, and other tools
- **Bridge System**: Communication between components
- **Skills Architecture**: Modular access to different operations
- **Logging System**: Display operational logs

## Technical Details

The interface is built with React and TypeScript, following modern best practices. It uses a modular architecture where each component has a specific responsibility and communicates through the bridge system.

## Dependencies

- React 18+
- TypeScript
- MCP server (running at `http://localhost:3001`)
- Jarvis OS bridge system
- Skills architecture for modular tool access

## Development

To add new features:
1. Create new components in the `components/` directory
2. Update the bridge system to handle new message types
3. Extend the MCP client with new tool execution methods
4. Update the UI to include new functionality

## Future Enhancements

- Real-time collaboration features
- Advanced code editing capabilities
- Integration with more MCP tools
- Enhanced voice recognition and synthesis
- Customizable UI themes