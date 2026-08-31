import '../styles/app.css'
import { createInertiaApp } from '@inertiajs/vue3'

createInertiaApp({
  pages: "../pages",

  // Every page sets its own <Head title>; this decides how it is dressed.
  // A bare "keepsake" on a page with no title of its own.
  title: (title) => (title ? `${title} · keepsake` : 'keepsake'),


  defaults: {
    form: {
      forceIndicesArrayFormatInFormData: false,
      withAllErrors: true,
    },
    visitOptions: () => {
      return { queryStringArrayFormat: "brackets" }
    },
  },
}).catch((error) => {
  // This ensures this entrypoint is only loaded on Inertia pages
  // by checking for the presence of the root element (#app by default).
  // Feel free to remove this `catch` if you don't need it.
  if (document.getElementById("app")) {
    throw error
  } else {
    console.error(
      "Missing root element.\n\n" +
      "If you see this error, it probably means you loaded Inertia.js on non-Inertia pages.\n" +
      'Consider moving <%= vite_javascript_tag "inertia" %> to the Inertia-specific layout instead.',
    )
  }
})
