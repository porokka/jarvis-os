import React, { useState, useRef, useEffect } from 'react';

interface Message {
  id: string;
  content: string;
  sender: 'user' | 'jarvis';
  timestamp: Date;
}

const ChatInterface = () => {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: '1',
      content: 'Hello! I\'m Jarvis. How can I help you with coding today?',
      sender: 'jarvis',
      timestamp: new Date()
    }
  ]);
  const [inputValue, setInputValue] = useState('');
  const [isListening, setIsListening] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSendMessage = () => {
    if (!inputValue.trim()) return;

    // Add user message
    const userMessage: Message = {
      id: Date.now().toString(),
      content: inputValue,
      sender: 'user',
      timestamp: new Date()
    };

    setMessages(prev => [...prev, userMessage]);
    setInputValue('');
    setIsLoading(true);

    // Simulate Jarvis response
    setTimeout(() => {
      const jarvisResponse: Message = {
        id: (Date.now() + 1).toString(),
        content: `I received your message: "${inputValue}". This is a simulated response from Jarvis. In a real implementation, this would connect to the Claude model and MCP tools.`,
        sender: 'jarvis',
        timestamp: new Date()
      };
      setMessages(prev => [...prev, jarvisResponse]);
      setIsLoading(false);
    }, 1000);
  };

  const handleVoiceInput = () => {
    setIsListening(!isListening);
    if (!isListening) {
      // Simulate voice input
      setTimeout(() => {
        setInputValue('This is a simulated voice input for testing the coding interface.');
        setIsListening(false);
      }, 2000);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  return (
    <div className="chat-interface">
      <div className="chat-header">
        <h3>Chat Interface</h3>
        <div className="chat-controls">
          <button
            className={`voice-button ${isListening ? 'listening' : ''}`}
            onClick={handleVoiceInput}
          >
            {isListening ? 'Listening...' : '🎤 Voice Input'}
          </button>
        </div>
      </div>

      <div className="messages-container">
        {messages.map((message) => (
          <div
            key={message.id}
            className={`message ${message.sender}`}
          >
            <div className="message-content">
              {message.content}
            </div>
            <div className="message-time">
              {message.timestamp.toLocaleTimeString()}
            </div>
          </div>
        ))}
        {isLoading && (
          <div className="message jarvis typing">
            <div className="message-content">
              <div className="typing-indicator">
                <span></span>
                <span></span>
                <span></span>
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="input-container">
        <textarea
          className="message-input"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyPress={handleKeyPress}
          placeholder="Type your message or use voice input..."
          rows={3}
        />
        <button
          className="send-button"
          onClick={handleSendMessage}
          disabled={isLoading}
        >
          Send
        </button>
      </div>
    </div>
  );
};

export { ChatInterface };