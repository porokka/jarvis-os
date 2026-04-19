import React from 'react';

interface LogDisplayProps {
  logs: string[];
}

const LogsDisplay: React.FC<LogDisplayProps> = ({ logs }) => {
  return (
    <div className="logs-display">
      <div className="logs-header">
        <h4>System Logs</h4>
      </div>
      <div className="logs-content">
        <pre className="logs-text">
          {logs.map((log, index) => (
            <div key={index} className="log-line">
              {log}
            </div>
          ))}
        </pre>
      </div>
    </div>
  );
};

export { LogsDisplay };