import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './components/App';
import './assets/fonts/fonts.css';
import './styles.css';

const root = document.getElementById('root');
if (!root) throw new Error('Brak elementu #root');

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
