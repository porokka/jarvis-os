import React, { useState, useEffect } from 'react';
import { CodeEditor } from './CodeEditor';
import { ChatInterface } from './ChatInterface';
import { LogsDisplay } from './LogsDisplay';

const CodingInterface = () => {
  const [isExpanded, setIsExpanded] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState<'editor' | 'chat'>('editor');

  // Simulate logs from the system
  useEffect(() => {
    const mockLogs = [
      '[INFO] System initialized',
      '[DEBUG] MCP server started on port 3001',
      '[INFO] Bridge connection established',
      '[DEBUG] Skills loaded: 13',
      '[INFO] File system access enabled',
      '[DEBUG] Git operations ready'
    ];
    setLogs(mockLogs);
  }, []);

  const toggleInterface = () => {
    setIsExpanded(!isExpanded);
  };

  return (
    <div className={`coding-interface ${isExpanded ? 'expanded' : 'collapsed'}`}>
      <div className="interface-header">
        <h2> Jarvis Coding Interface</h2>
        <button onClick={toggleInterface} className="toggle-button">
          {isExpanded ? 'Collapse' : 'Expand'}
        </button>
      </div>

      {isExpanded && (
        <div className="interface-content">
          <div className="logs-panel">
            <LogsDisplay logs={logs} />
          </div>

          <div className="main-content">
            <div className="tabs">
              <button
                className={activeTab === 'editor' ? 'active' : ''}
                onClick={() => setActiveTab('editor')}
              >
                Code Editor
              </button>
              <button
                className={activeTab === 'chat' ? 'active' : ''}
                onClick={() => setActiveTab('chat')}
              >
                Chat Interface
              </button>
            </div>

            <div className="panel-content">
              {activeTab === 'editor' ? (
                <CodeEditor />
              ) : (
                <ChatInterface />
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default CodingInterface;