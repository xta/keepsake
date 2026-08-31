<script setup>
import { Link, useForm, router } from '@inertiajs/vue3'
import { computed } from 'vue'
import AppLayout from '../../layouts/AppLayout.vue'
defineOptions({ layout: AppLayout })

const props = defineProps({
  library: Object,
  providers: Object,
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
</script>

<template>
  <div style="max-width: 34rem; margin: 0 auto;">
    <div class="page-head">
      <div class="grow">
        <h1>{{ editing ? 'Edit library' : 'Add a library' }}</h1>
        <p class="sub">Credentials are encrypted before they are stored, and the secret is never sent back to your browser.</p>
      </div>
    </div>

    <div v-if="library?.lastError" class="flash flash-alert">
      Last connection attempt failed: {{ library.lastError }}
    </div>

    <form class="card card-pad" @submit.prevent="submit">
      <div class="field">
        <label for="label">Name</label>
        <input id="label" v-model="form.label" type="text" required placeholder="Family videos" />
        <div class="hint">Just a label for you. Any name works.</div>
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
        <div class="hint">Must be https. Addresses on private networks are refused.</div>
        <div v-if="form.errors.endpoint" class="err">{{ form.errors.endpoint }}</div>
      </div>

      <div v-if="shows('account_id')" class="field">
        <label for="account">Cloudflare account id</label>
        <input id="account" v-model="form.account_id" type="text"
               :placeholder="library ? 'leave blank to keep the current endpoint' : ''" />
        <div class="hint">Your endpoint becomes https://&lt;account id&gt;.r2.cloudflarestorage.com</div>
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
        <div class="hint">Only if the library lives under a subpath rather than at the bucket root.</div>
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
        <div class="hint" v-if="editing">Stored and encrypted. Leave blank to keep the current key.</div>
        <div class="hint" v-else>{{ meta.key_help }}</div>
        <div v-if="form.errors.secret_access_key" class="err">{{ form.errors.secret_access_key }}</div>
      </div>

      <div class="field">
        <label for="access">This key can</label>
        <select id="access" v-model="form.access_level">
          <option value="read_only">Read only &mdash; recommended</option>
          <option value="read_write">Read and write</option>
        </select>
        <div class="hint">
          Viewing only needs read. A read-only key scoped to this one bucket
          means a breach of this app cannot damage your archive.
        </div>
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
        <Link class="btn" :href="editing ? `/libraries/${library.id}` : '/libraries'">Cancel</Link>
        <button v-if="editing" type="button" class="btn btn-danger" style="margin-left: auto" @click="destroy">
          Remove
        </button>
      </div>
      <p v-if="editing" class="hint" style="margin-top: .75rem">
        Removing a library deletes its stored credentials and cached catalog here.
        It never touches the bucket.
      </p>
    </form>
  </div>
</template>
