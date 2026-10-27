import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './app.jsx';
import { AuthProvider } from './auth/AuthContext.jsx';
import './styles/tokens.css';
import './styles/app.css';

// Light theme everywhere (black and orange brand colours), whatever the system setting.
document.documentElement.dataset.theme = 'light';

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
