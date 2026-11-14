import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource/nunito-sans/400.css'
import '@fontsource/nunito-sans/600.css'
import '@fontsource/nunito-sans/700.css'
import '@fontsource/bricolage-grotesque/600.css'
import '@fontsource/bricolage-grotesque/700.css'
import '@fontsource/ibm-plex-mono/400.css'
import '@fontsource/ibm-plex-mono/500.css'
import './index.css'
import { setProduct, setSignupOpen } from './utils/product'
import App from './App.jsx'
import { api } from './api'
import { setStatusLabels } from './utils/statusLabels'
import { setCategoryLabels } from './utils/categories'

function render() {
  createRoot(document.getElementById('root')).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}

// Admin-configured status labels and the category labels; fall back to
// the defaults if the backend can't be reached rather than blocking the page.
api
  .meta()
  .then((meta) => {
    setStatusLabels(meta.status_labels)
    setCategoryLabels(meta.category_labels)
    setProduct(meta.product)
    setSignupOpen(meta.signup_open)
  })
  .catch(() => {})
  .finally(render)
