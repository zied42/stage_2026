import React, { useState, useRef, useEffect } from 'react';

export default function BlueprintChatbot({ blueprintId, blueprintData, predictions }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef(null);

  const suggestedQuestions = [
    { icon: '⚠️', text: 'Why is this blueprint risky?' },
    { icon: '📋', text: 'Summarize the specification' },
    { icon: '🔄', text: 'What could cause excessive rework?' },
    { icon: '📊', text: 'What are the main risk factors?' }
  ];

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading]);

  const handleSend = async (text) => {
    const messageText = typeof text === 'string' ? text : input;
    if (!messageText || !messageText.trim()) return;

    const userMessage = { role: 'user', content: messageText.trim() };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setLoading(true);

    try {
      if (!blueprintId) {
        throw new Error("Please select a blueprint first.");
      }
      const parts = blueprintId.split('::');
      if (parts.length < 2) {
        throw new Error("Invalid blueprint identifier.");
      }
      const [project, name] = parts;
      const res = await fetch(`http://localhost:3001/api/blueprints/${encodeURIComponent(project)}/${encodeURIComponent(name)}/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ message: messageText.trim(), predictions: predictions })
      });
      
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || `Server responded with status ${res.status}`);
      }
      
      setMessages(prev => [...prev, { role: 'assistant', content: data.response || "No response received." }]);
    } catch (err) {
      console.error(err);
      setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${err.message}` }]);
    } finally {
      setLoading(false);
    }
  };

  const handleClearChat = () => {
    setMessages([]);
  };

  return (
    <div className="card chatCard">
      {/* Header */}
      <div className="chatHeader">
        <div className="chatHeaderLeft">
          <div className="chatAvatarHeader">
            <span className="aiSparkleIcon">✨</span>
          </div>
          <div>
            <div className="chatTitle">AI Assistant</div>
            <div className="chatSubtitle">
              <span className="statusDot active"></span> Grounded Risk Insights
            </div>
          </div>
        </div>
        {messages.length > 0 && (
          <button className="chatResetBtn" onClick={handleClearChat} title="Clear conversation">
            ↺ Reset
          </button>
        )}
      </div>

      {/* Messages Area */}
      <div className="chatConversation">
        {messages.length === 0 ? (
          <div className="chatWelcome">
            <div className="welcomeIcon">🤖</div>
            <div className="welcomeTitle">How can I help with this blueprint?</div>
            <div className="welcomeDesc">
              Ask about development risks, specification quality, historical patterns, or recommended actions.
            </div>
            <div className="chatChipsContainer">
              <div className="chipsLabel">Suggested Prompts:</div>
              <div className="chatChips">
                {suggestedQuestions.map((q, idx) => (
                  <button 
                    key={idx} 
                    className="chatChip" 
                    onClick={() => handleSend(q.text)} 
                    disabled={loading}
                  >
                    <span className="chipIcon">{q.icon}</span>
                    <span className="chipText">{q.text}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div className="chatMessageList">
            {messages.map((msg, idx) => (
              <div key={idx} className={`chatMessageRow ${msg.role}`}>
                <div className="chatMsgAvatar">
                  {msg.role === 'user' ? '👤' : '✨'}
                </div>
                <div className={`chatBubble ${msg.role}`}>
                  <div className="chatSenderName">
                    {msg.role === 'user' ? 'You' : 'AI Assistant'}
                  </div>
                  <div className="chatBubbleContent">
                    {msg.content}
                  </div>
                </div>
              </div>
            ))}
            {loading && (
              <div className="chatMessageRow assistant">
                <div className="chatMsgAvatar">✨</div>
                <div className="chatBubble assistant loading">
                  <div className="typingIndicator">
                    <span></span>
                    <span></span>
                    <span></span>
                  </div>
                  <span className="loadingText">Analyzing blueprint context...</span>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Quick Prompts Bar (when conversation is active) */}
      {messages.length > 0 && (
        <div className="chatQuickChips">
          {suggestedQuestions.map((q, idx) => (
            <button 
              key={idx} 
              className="chatQuickChip" 
              onClick={() => handleSend(q.text)} 
              disabled={loading}
            >
              {q.icon} {q.text}
            </button>
          ))}
        </div>
      )}

      {/* Input Row */}
      <div className="chatInputWrapper">
        <div className="chatInputBox">
          <input
            className="chatInputField"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !loading && input.trim()) {
                handleSend(input);
              }
            }}
            placeholder="Ask AI about this blueprint..."
            disabled={loading}
          />
          <button 
            className="chatSubmitBtn" 
            onClick={() => handleSend(input)} 
            disabled={loading || !input.trim()}
            title="Send Message"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <line x1="22" y1="2" x2="11" y2="13"></line>
              <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
