<script setup>
import { Head, Link, useForm, router } from '@inertiajs/vue3'
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
const editing = ref(false)
const form = useForm({
  title: props.item.title || '',
  recorded_at: props.item.recordedAt || '',
  location: props.item.sidecar?.location || '',
  notes: props.item.sidecar?.notes || '',
})

const enriching = ref(false)
function enrich() {
  enriching.value = true
  router.post(`/libraries/${props.library.id}/items/${props.item.id}/enrich`, {}, {
    onFinish: () => { enriching.value = false },
  })
}

// Worth offering only while something is actually missing.
const incomplete = computed(() =>
  !props.item.recordedAt || !props.item.durationS || (!props.item.thumbnailUrl && props.item.kind === 'video')
)

function save() {
  form.patch(`/libraries/${props.library.id}/items/${props.item.id}`, {
    onSuccess: () => { editing.value = false },
  })
}

const extra = computed(() =>
  Object.entries(props.item.sidecar || {})
    .filter(([k, v]) => !KNOWN.has(k) && v != null && v !== '' && !(Array.isArray(v) && !v.length))
)
</script>

<template>
  <Head :title="item.displayTitle" />
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
    <div v-if="editing" class="card card-pad">
      <h2 style="margin-bottom: .9rem">Edit</h2>
      <div class="field">
        <label for="title">Title</label>
        <input id="title" v-model="form.title" type="text" autofocus />
      </div>
      <div class="field">
        <label for="recorded">Recorded</label>
        <input id="recorded" v-model="form.recorded_at" type="text" placeholder="YYYY-MM-DD" />
        <div class="hint">Leave blank if you do not know.</div>
      </div>
      <div class="field">
        <label for="location">Location</label>
        <input id="location" v-model="form.location" type="text" />
      </div>
      <div class="field">
        <label for="notes">Notes</label>
        <textarea id="notes" v-model="form.notes" rows="3"></textarea>
      </div>
      <div class="row">
        <button class="btn btn-primary" :disabled="form.processing" @click="save">Save</button>
        <button class="btn" type="button" @click="editing = false">Cancel</button>
      </div>
      <p class="hint" style="margin-top: .75rem">
        Saved into the bucket, alongside the video.
      </p>
    </div>

    <div v-else class="card card-pad">
      <div class="row" style="justify-content: space-between; margin-bottom: .9rem">
        <h2>Details</h2>
        <button v-if="library.writable" class="btn btn-sm" @click="editing = true">Edit</button>
      </div>
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
      <div class="row" style="margin: 1.25rem 0 0">
        <a class="btn btn-sm" :href="item.downloadUrl">Download original</a>
        <!-- Only while something is missing, and only when the key can write.
             Fills the date, the runtime and the still, whichever are absent. -->
        <button v-if="library.writable && incomplete"
                class="btn btn-sm" :disabled="enriching" @click="enrich">
          {{ enriching ? 'Reading…' : 'Read from file' }}
        </button>
      </div>
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
