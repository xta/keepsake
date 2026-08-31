<script setup>
import { Link, router } from '@inertiajs/vue3'
import { ref } from 'vue'
import AppLayout from '../../layouts/AppLayout.vue'
import { bytes, duration, recordedAt, timeAgo } from '../../lib/format'
defineOptions({ layout: AppLayout })

const props = defineProps({
  library: Object,
  items: Array,
  page: Number,
  totalPages: Number,
  catalogMissing: Boolean,
  error: String,
})

// A thumbnail that will not decode should degrade to the filename card, not
// leave a broken image icon in the grid.
const brokenThumbs = ref(new Set())
function thumbBroke(id) { brokenThumbs.value = new Set(brokenThumbs.value).add(id) }
function hasThumb(item) { return item.thumbnailUrl && !brokenThumbs.value.has(item.id) }

const refreshing = ref(false)
function refresh() {
  refreshing.value = true
  router.post(`/libraries/${props.library.id}/refresh`, {}, {
    onFinish: () => { refreshing.value = false },
  })
}
</script>

<template>
  <div class="page-head">
    <div class="grow">
      <h1>{{ library.label }}</h1>
      <p class="sub">
        <span class="mono">{{ library.bucket }}<span v-if="library.prefix">/{{ library.prefix }}</span></span>
        <template v-if="library.itemCount != null">
          &middot; {{ library.itemCount }} {{ library.itemCount === 1 ? 'item' : 'items' }}
        </template>
        <template v-if="library.totalBytes"> &middot; {{ bytes(library.totalBytes) }}</template>
      </p>
      <!-- SPEC calls a stale index.json a cosmetic bug rather than data loss,
           so show its age plainly instead of pretending it is live. -->
      <p v-if="library.generatedAt" class="sub">
        Catalog built {{ timeAgo(library.generatedAt) }}
      </p>
    </div>
    <div class="row">
      <button class="btn" :disabled="refreshing" @click="refresh">
        {{ refreshing ? 'Refreshing…' : 'Refresh' }}
      </button>
      <Link class="btn" :href="`/libraries/${library.id}/edit`">Settings</Link>
    </div>
  </div>

  <div v-if="error" class="flash flash-alert">{{ error }}</div>

  <div v-if="catalogMissing" class="empty">
    <h2>This bucket has no catalog yet</h2>
    <p>
      keepsake reads a single <code>index.json</code> at the bucket root, which
      lists every file and its metadata. This bucket does not have one.
    </p>
    <p>
      Build it with the command line tool: <code>keepsake sync --apply</code>.
      Your videos are not lost &mdash; they are simply not catalogued yet.
    </p>
  </div>

  <div v-else-if="!items.length" class="empty">
    <h2>Nothing here yet</h2>
    <p>The catalog is empty. Upload some video and run <code>keepsake sync --apply</code>.</p>
  </div>

  <div v-else class="grid">
    <Link v-for="item in items" :key="item.id" :href="`/libraries/${library.id}/items/${item.id}`" class="tile">
      <div class="thumb">
        <img v-if="hasThumb(item)" :src="item.thumbnailUrl" :alt="item.displayTitle"
             loading="lazy" @error="thumbBroke(item.id)" />
        <!-- No thumbnail is normal: SPEC makes them optional, and the CLI
             skips images entirely, so every HEIC lands here. -->
        <div v-else class="thumb-fallback">
          <span class="ext">{{ item.formatLabel }}</span>
        </div>

        <span v-if="item.durationS" class="badge">{{ duration(item.durationS) }}</span>
        <span v-if="!item.playable" class="badge badge-warn">download only</span>
      </div>

      <div class="meta">
        <div class="title" :class="{ untitled: item.untitled }">{{ item.displayTitle }}</div>
        <div class="sub">
          <span v-if="item.recordedAt">{{ recordedAt(item.recordedAt) }}</span>
          <span v-else class="muted">no date</span>
          <span v-if="item.sizeBytes"> &middot; {{ bytes(item.sizeBytes) }}</span>
        </div>
      </div>
    </Link>
  </div>

  <div v-if="totalPages > 1" class="row" style="justify-content: center; margin-top: 2rem">
    <Link v-if="page > 1" class="btn" :href="`/libraries/${library.id}?page=${page - 1}`">Previous</Link>
    <span class="muted" style="font-size: .88rem">Page {{ page }} of {{ totalPages }}</span>
    <Link v-if="page < totalPages" class="btn" :href="`/libraries/${library.id}?page=${page + 1}`">Next</Link>
  </div>
</template>

<style scoped>
.grid {
  display: grid; gap: 1.1rem;
  grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr));
}
.tile { text-decoration: none; color: inherit; display: block; }
.thumb {
  position: relative; aspect-ratio: 16 / 10; border-radius: var(--radius);
  overflow: hidden; background: var(--surface-2); border: 1px solid var(--border);
}
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.tile:hover .thumb { border-color: var(--accent); }
.thumb-fallback {
  width: 100%; height: 100%; display: grid; place-items: center;
}
.ext {
  font: 600 .8rem/1 ui-monospace, SFMono-Regular, Menlo, monospace;
  letter-spacing: .08em; color: var(--muted);
  border: 1px solid var(--border); border-radius: 6px; padding: .35rem .5rem;
}
.badge {
  position: absolute; right: .4rem; bottom: .4rem;
  background: rgba(0, 0, 0, .72); color: #fff;
  font-size: .72rem; padding: .1rem .35rem; border-radius: 4px;
}
.badge-warn { left: .4rem; right: auto; background: rgba(0, 0, 0, .72); }
.meta { margin-top: .5rem; }
.title { font-weight: 550; font-size: .92rem; overflow-wrap: anywhere; }
.title.untitled { font-weight: 450; color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .85rem; }
.sub { font-size: .8rem; color: var(--muted); margin-top: .15rem; }
</style>
