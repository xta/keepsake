<script setup>
import { Head, Link } from '@inertiajs/vue3'
import AppLayout from '../../layouts/AppLayout.vue'
import { bytes, timeAgo } from '../../lib/format'
defineOptions({ layout: AppLayout })

defineProps({ libraries: Array })
</script>

<template>
  <Head title="Libraries" />
  <div class="page-head">
    <div class="grow">
      <h1>Your libraries</h1>
      
    </div>
    <Link class="btn btn-primary" href="/libraries/new">Add a library</Link>
  </div>

  <div v-if="!libraries.length" class="empty">
    <h2>No libraries yet</h2>
    <p>
      Connect a bucket to see what is in it. Use a read-only key if you can.
    </p>
    <p style="margin-top: 1.25rem">
      <Link class="btn btn-primary" href="/libraries/new">Add your first library</Link>
    </p>
  </div>

  <div v-else class="lib-grid">
    <div v-for="lib in libraries" :key="lib.id" class="card card-pad lib-card">
      <div class="row" style="justify-content: space-between; align-items: flex-start">
        <h2><Link :href="`/libraries/${lib.id}`">{{ lib.label }}</Link></h2>
        <span class="pill">{{ lib.providerShortLabel || lib.provider }}</span>
      </div>

      <div class="mono muted" style="margin-top: .35rem; overflow-wrap: anywhere">
        {{ lib.bucket }}<span v-if="lib.prefix">/{{ lib.prefix }}</span>
      </div>

      <div class="lib-stats">
        <template v-if="lib.itemCount != null">
          <span>{{ lib.itemCount }} {{ lib.itemCount === 1 ? 'item' : 'items' }}</span>
          <span v-if="lib.totalBytes">{{ bytes(lib.totalBytes) }}</span>
        </template>
        <span v-else class="muted">not fetched yet</span>
      </div>

      <div class="lib-foot">
        <span v-if="lib.lastError" class="pill pill-warn">connection error</span>
        <span v-else-if="lib.accessLevel === 'read_only'" class="pill">read-only</span>
        <span v-if="lib.generatedAt" class="muted" style="font-size: .8rem">
          catalog built {{ timeAgo(lib.generatedAt) }}
        </span>
        <!-- Always reachable from here. A misconfigured library cannot open
             its own grid, and that is exactly when settings are needed.
             `from` tells that page to send you back here, not onward. -->
        <Link class="icon-btn" :href="`/libraries/${lib.id}/edit?from=index`" title="Settings" aria-label="Settings">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"
               stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
        </Link>
      </div>

      <p v-if="lib.lastError" class="muted" style="font-size: .8rem; margin: .6rem 0 0">
        {{ lib.lastError }}
      </p>
    </div>
  </div>
</template>

<style scoped>
.lib-grid {
  display: grid; gap: 1rem;
  grid-template-columns: repeat(auto-fill, minmax(17rem, 1fr));
}
/* The whole card is the target, not just the title. The title's link is
   stretched over the card with a pseudo-element, which keeps one real anchor
   in the markup -- so it still reads as a single link to a screen reader and
   the URL still shows on hover. */
.lib-card { position: relative; transition: border-color .12s, box-shadow .12s; }
.lib-card:hover { border-color: var(--accent); box-shadow: 0 2px 6px rgba(28, 26, 24, .09), 0 8px 20px rgba(28, 26, 24, .06); }
.lib-card h2 a { text-decoration: none; }
.lib-card h2 a::after { content: ""; position: absolute; inset: 0; border-radius: var(--radius); }
.lib-card:hover h2 a { text-decoration: underline; }

/* Anything genuinely clickable has to sit above that overlay. */
.icon-btn {
  position: relative; z-index: 1; margin-left: auto;
  display: inline-flex; align-items: center; justify-content: center;
  width: 1.9rem; height: 1.9rem; border-radius: 7px;
  color: var(--muted); border: 1px solid transparent;
}
.icon-btn:hover { color: var(--text); background: var(--surface-2); border-color: var(--border); }
.lib-stats { display: flex; gap: .75rem; margin-top: .9rem; font-size: .88rem; }
.lib-foot { display: flex; gap: .5rem; align-items: center; margin-top: .9rem; flex-wrap: wrap; }
</style>
