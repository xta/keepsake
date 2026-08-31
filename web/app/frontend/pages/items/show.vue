<script setup>
import { Link } from '@inertiajs/vue3'
import { ref, computed } from 'vue'
import AppLayout from '../../layouts/AppLayout.vue'
import { bytes, duration, recordedAt } from '../../lib/format'
defineOptions({ layout: AppLayout })

const props = defineProps({
  library: Object,
  item: Object,
  prevId: Number,
  nextId: Number,
})

// Two-stage detection, because neither half is sufficient alone.
//
// `item.playable` is the server's extension blocklist: formats no browser
// renders. But codec support inside a container varies by browser -- a .mov
// may hold anything -- so a static table cannot be complete. This flag is the
// other half: if the element itself fails, fall back to the same card.
const failed = ref(false)
const showPlayer = computed(() => props.item.playable && !failed.value && props.item.mediaUrl)

// Fields this app has no column for. SPEC requires unknown fields to survive a
// round trip, so the one page that could show them, does.
const KNOWN = new Set([
  'schema', 'id', 'file', 'title', 'recorded_at', 'uploaded_at', 'duration_s',
  'size_bytes', 'media_type', 'sha256', 'thumbnail', 'path',
])
const extra = computed(() =>
  Object.entries(props.item.sidecar || {})
    .filter(([k, v]) => !KNOWN.has(k) && v != null && v !== '' && !(Array.isArray(v) && !v.length))
)
</script>

<template>
  <div class="page-head">
    <div class="grow">
      <p class="sub" style="margin: 0 0 .3rem">
        <Link :href="`/libraries/${library.id}`">&larr; {{ library.label }}</Link>
      </p>
      <h1 :class="{ untitled: item.untitled }">{{ item.displayTitle }}</h1>
      <p class="sub mono">{{ item.path }}</p>
    </div>
    <div class="row">
      <Link v-if="prevId" class="btn btn-sm" :href="`/libraries/${library.id}/items/${prevId}`">&larr; Previous</Link>
      <Link v-if="nextId" class="btn btn-sm" :href="`/libraries/${library.id}/items/${nextId}`">Next &rarr;</Link>
    </div>
  </div>

  <div class="stage">
    <video v-if="showPlayer" :src="item.mediaUrl" controls preload="metadata"
           :poster="item.thumbnailUrl || undefined" @error="failed = true"></video>

    <div v-else class="cannot-play">
      <img v-if="item.thumbnailUrl" :src="item.thumbnailUrl" :alt="item.displayTitle" class="poster" />
      <div class="cannot-body">
        <h2>{{ failed ? 'Your browser could not play this file' : `This browser cannot play ${item.formatLabel} files` }}</h2>
        <p class="muted">Files are kept as uploaded, never converted. Download it to watch elsewhere.</p>
        <!-- A signed content-disposition is what makes this download rather
             than navigate: cross-origin `download` attributes are ignored. -->
        <a class="btn btn-primary" :href="item.downloadUrl">Download {{ item.formatLabel }}</a>
      </div>
    </div>
  </div>

  <div class="detail">
    <div class="card card-pad">
      <h2 style="margin-bottom: .9rem">Details</h2>
      <dl>
        <template v-if="item.recordedAt"><dt>Recorded</dt><dd>{{ recordedAt(item.recordedAt) }}</dd></template>
        <template v-if="item.durationS"><dt>Length</dt><dd>{{ duration(item.durationS) }}</dd></template>
        <template v-if="item.sizeBytes"><dt>Size</dt><dd>{{ bytes(item.sizeBytes) }}</dd></template>
        <template v-if="item.mediaType"><dt>Type</dt><dd class="mono">{{ item.mediaType }}</dd></template>
        <template v-if="item.uploadedAt"><dt>Uploaded</dt><dd>{{ new Date(item.uploadedAt).toLocaleString() }}</dd></template>
        <template v-for="[key, value] in extra" :key="key">
          <dt>{{ key.replace(/_/g, ' ') }}</dt>
          <dd>{{ Array.isArray(value) ? value.join(', ') : value }}</dd>
        </template>
      </dl>
      <p style="margin: 1.25rem 0 0">
        <a class="btn btn-sm" :href="item.downloadUrl">Download original</a>
      </p>
    </div>
  </div>
</template>

<style scoped>
.stage {
  background: #000; border-radius: var(--radius); overflow: hidden;
  border: 1px solid var(--border); margin-bottom: 1.5rem;
}
.stage video { width: 100%; max-height: 72vh; display: block; }
.cannot-play {
  display: flex; gap: 1.5rem; align-items: center; flex-wrap: wrap;
  padding: 1.75rem; background: var(--surface);
}
.poster { width: 15rem; border-radius: 8px; border: 1px solid var(--border); }
.cannot-body { flex: 1; min-width: 16rem; }
.cannot-body h2 { margin-bottom: .5rem; }
.cannot-body p { margin: 0 0 1.1rem; font-size: .9rem; max-width: 34rem; }
.detail { max-width: 34rem; }
h1.untitled { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 1.15rem; color: var(--muted); }
dl { display: grid; grid-template-columns: auto 1fr; gap: .5rem 1.25rem; margin: 0; font-size: .9rem; }
dt { color: var(--muted); }
dd { margin: 0; overflow-wrap: anywhere; }
</style>
