<script setup>
import { Head, Link, useForm, router } from '@inertiajs/vue3'
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { bytes, timeAgo } from '../../lib/format'
import AppLayout from '../../layouts/AppLayout.vue'
defineOptions({ layout: AppLayout })

const props = defineProps({
  library: Object,
  providers: Object,
  backTo: Object,
  from: String,
})

const editing = computed(() => !!props.library)

const form = useForm({
  label: props.library?.label || '',
  provider: props.library?.provider || 'b2',
  endpoint: props.library?.endpoint || '',
  region: props.library?.region || '',
  account_id: '',
  bucket: props.library?.bucket || '',
  prefix: props.library?.prefix || '',
  force_path_style: props.library?.forcePathStyle || false,
  access_level: props.library?.accessLevel || 'read_only',
  access_key_id: props.library?.accessKeyId || '',
  secret_access_key: '',
})

const meta = computed(() => props.providers[form.provider] || { fields: [] })
const shows = (field) => meta.value.fields?.includes(field)

function submit() {
  if (editing.value) form.patch(`/libraries/${props.library.id}`)
  else form.post('/libraries')
}

// Sends the current form values, so what gets tested is what you are looking
// at rather than whatever was last saved.
function verify() {
  form.post(`/libraries/${props.library.id}/verify`)
}

function destroy() {
  router.delete(`/libraries/${props.library.id}`)
}

// Refresh and Scan navigate, which throws away anything typed into the form
// below. Rather than silently losing it, they wait until there is nothing to
// lose. `isDirty` is Inertia's own comparison against the values we started
// with, so saving clears it.
const blocked = computed(() => editing.value && form.isDirty)

const refreshing = ref(false)
function refresh() {
  refreshing.value = true
  router.post(`/libraries/${props.library.id}/refresh`, { from: props.from }, {
    onFinish: () => { refreshing.value = false },
  })
}

// A sweep runs in the background, so the page asks how it is going.
let poll = null
onMounted(() => {
  if (!props.library?.sweeping) return
  poll = setInterval(() => router.reload({ only: ["library"] }), 3000)
})
onUnmounted(() => { if (poll) clearInterval(poll) })
</script>

<template>
  <Head :title="editing ? `${library.label} settings` : 'Add a library'" />
  <div style="max-width: 34rem; margin: 0 auto;">
    <p class="back">
      <Link :href="backTo.href">&larr; {{ backTo.label }}</Link>
    </p>

    <div class="page-head">
      <div class="grow">
        <h1>{{ editing ? 'Settings' : 'Add a library' }}</h1>
        
      </div>
    </div>

    <div v-if="library?.lastError" class="flash flash-alert">
      Last connection attempt failed: {{ library.lastError }}
    </div>

    <template v-if="editing">
      <section class="card card-pad">
        <h2>Catalog</h2>
        <p class="sub">
          <template v-if="library.itemCount != null">
            {{ library.itemCount }} {{ library.itemCount === 1 ? 'item' : 'items' }}<template
              v-if="library.totalBytes"> &middot; {{ bytes(library.totalBytes) }}</template>
          </template>
          <template v-else>Not fetched yet.</template>
          <template v-if="library.generatedAt"> &middot; built {{ timeAgo(library.generatedAt) }}</template>
        </p>
        <p class="hint">Re-reads the index from the bucket. Nothing is written.</p>
        <button type="button" class="btn" :disabled="refreshing || blocked" @click="refresh">
          {{ refreshing ? 'Refreshing…' : 'Refresh catalog' }}
        </button>
      </section>

      <!-- Writing is only offered when the stored key can write. A read-only
           library is not shown a button it would be refused. -->
      <section v-if="library.writable" class="card card-pad">
        <h2>Scan for new files</h2>
        <p class="hint">
          Finds media added by other tools, fills in dates, runtimes and
          thumbnails, and rebuilds the index.
        </p>

        <div v-if="library.sweeping" class="flash flash-notice">
          Scanning&hellip; {{ library.sweepMessage }}
        </div>
        <div v-else-if="library.sweepState === 'failed'" class="flash flash-alert">
          Last scan failed: {{ library.sweepMessage }}
        </div>
        <p v-else-if="library.sweepState === 'done' && library.sweepMessage" class="sub">
          Last scan: {{ library.sweepMessage
          }}<template v-if="library.sweepFinishedAt"> &middot; {{ timeAgo(library.sweepFinishedAt) }}</template>
        </p>

        <Link v-if="!library.sweeping && !blocked" class="btn" :href="`/libraries/${library.id}/sweep${from ? `?from=${from}` : ''}`">
          Scan for new files
        </Link>
        <button v-else-if="!library.sweeping" type="button" class="btn" disabled>Scan for new files</button>
      </section>

      <p v-if="blocked" class="hint" style="margin: -.4rem 0 1rem">
        Save or discard your changes below to refresh or scan.
      </p>
    </template>

    <form class="card card-pad" @submit.prevent="submit">
      <div class="field">
        <label for="label">Name</label>
        <input id="label" v-model="form.label" type="text" required placeholder="Family videos" />
        <div class="hint">Name of this library.</div>
        <div v-if="form.errors.label" class="err">{{ form.errors.label }}</div>
      </div>

      <div class="field">
        <label for="provider">Provider</label>
        <select id="provider" v-model="form.provider">
          <option v-for="(info, key) in providers" :key="key" :value="key">{{ info.label }}</option>
        </select>
      </div>

      <div v-if="shows('endpoint')" class="field">
        <label for="endpoint">Endpoint</label>
        <input id="endpoint" v-model="form.endpoint" type="text" placeholder="https://s3.example.com" />
        <div class="hint">https only.</div>
        <div v-if="form.errors.endpoint" class="err">{{ form.errors.endpoint }}</div>
      </div>

      <div v-if="shows('account_id')" class="field">
        <label for="account">Cloudflare account id</label>
        <input id="account" v-model="form.account_id" type="text"
               :placeholder="library ? 'leave blank to keep the current endpoint' : ''" />
        <div class="hint">Becomes https://&lt;account id&gt;.r2.cloudflarestorage.com</div>
      </div>

      <div v-if="shows('region')" class="field">
        <label for="region">{{ meta.region_label || 'Region' }}</label>
        <input id="region" v-model="form.region" type="text" required />
        <div class="hint">{{ meta.region_hint }}</div>
        <div v-if="form.errors.region" class="err">{{ form.errors.region }}</div>
      </div>

      <div class="field">
        <label for="bucket">{{ form.provider === 'local' ? 'Directory path' : 'Bucket name' }}</label>
        <input id="bucket" v-model="form.bucket" type="text" required />
        <div v-if="form.errors.bucket" class="err">{{ form.errors.bucket }}</div>
      </div>

      <div class="field">
        <label for="prefix">Key prefix <span class="muted">(optional)</span></label>
        <input id="prefix" v-model="form.prefix" type="text" placeholder="archive/" />
        <div class="hint">Use if your files are under a subpath in the bucket.</div>
      </div>

      <hr style="border: 0; border-top: 1px solid var(--border); margin: 1.5rem 0" />

      <div class="field">
        <label for="key">Access key id</label>
        <input id="key" v-model="form.access_key_id" type="text" required autocomplete="off" />
        <div v-if="form.errors.access_key_id" class="err">{{ form.errors.access_key_id }}</div>
      </div>

      <div class="field">
        <label for="secret">Secret access key</label>
        <input id="secret" v-model="form.secret_access_key" type="password" autocomplete="off"
               :required="!editing" :placeholder="editing ? library.secretHint : ''" />
        <div class="hint" v-if="editing">Leave blank to keep the current key.</div>
        <div class="hint" v-else>{{ meta.key_help }}</div>
        <div v-if="form.errors.secret_access_key" class="err">{{ form.errors.secret_access_key }}</div>
      </div>

      <div class="field">
        <label for="access">This key can</label>
        <select id="access" v-model="form.access_level">
          <option value="read_only">Read only</option>
          <option value="read_write">Read and write</option>
        </select>
        <div class="hint">Read-only is enough to view and download.</div>
      </div>

      <div v-if="form.provider === 'other'" class="field">
        <label class="checkbox">
          <input type="checkbox" v-model="form.force_path_style" />
          <span>Use path-style addressing <span class="muted">(needed by MinIO and some others)</span></span>
        </label>
      </div>

      <div class="row" style="margin-top: 1.5rem">
        <button class="btn btn-primary" :disabled="form.processing">
          {{ editing ? 'Save changes' : 'Add library' }}
        </button>
        <button v-if="editing" type="button" class="btn" :disabled="form.processing" @click="verify">Test connection</button>
        <Link class="btn" :href="backTo.href">Cancel</Link>
        <button v-if="editing" type="button" class="btn btn-danger" style="margin-left: auto" @click="destroy">
          Remove
        </button>
      </div>
      <p v-if="editing" class="hint" style="margin-top: .75rem">
        Removes this library from keepsake. Nothing in the bucket is deleted.
      </p>
    </form>
  </div>
</template>

<style scoped>
.back { font-size: .85rem; margin: 0 0 1rem; }
.back a { color: var(--muted); text-decoration: none; }
.back a:hover { color: var(--text); text-decoration: underline; }
section { margin-bottom: 1rem; }
section h2 { font-size: 1rem; margin: 0 0 .35rem; }
.sub { font-size: .85rem; color: var(--muted); margin: .2rem 0; }
</style>
