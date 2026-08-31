<script setup>
import { Link, router } from '@inertiajs/vue3'
import { ref } from 'vue'
import AppLayout from '../../layouts/AppLayout.vue'
import { bytes, recordedAt } from '../../lib/format'
defineOptions({ layout: AppLayout })

const props = defineProps({
  library: Object,
  adoptable: Array,
  alreadyIndexed: Number,
  problems: Array,
})

const running = ref(false)
function apply() {
  running.value = true
  router.post(`/libraries/${props.library.id}/sweep`, {}, {
    onFinish: () => { running.value = false },
  })
}
</script>

<template>
  <div class="page-head">
    <div class="grow">
      <p class="sub" style="margin: 0 0 .3rem">
        <Link :href="`/libraries/${library.id}`">&larr; {{ library.label }}</Link>
      </p>
      <h1>Scan for new files</h1>
      <p class="sub">
        Finds media uploaded by anything else &mdash; a phone app, another
        client &mdash; and writes the metadata keepsake needs.
      </p>
    </div>
  </div>

  <div v-if="!adoptable.length && !problems.length" class="empty">
    <h2>Everything is catalogued</h2>
    <p>All {{ alreadyIndexed }} files in this bucket already have metadata.</p>
    <p style="margin-top: 1.25rem">
      <Link class="btn" :href="`/libraries/${library.id}`">Back to the library</Link>
    </p>
  </div>

  <template v-else>
    <div v-if="adoptable.length" class="card card-pad" style="margin-bottom: 1.5rem">
      <h2>{{ adoptable.length }} new {{ adoptable.length === 1 ? 'file' : 'files' }}</h2>
      <p class="muted" style="font-size: .88rem; margin: .4rem 0 1rem">
        Each gets a sidecar recording its name, size, type and when it landed.
        Titles and dates are left blank &mdash; add them afterwards.
      </p>

      <ul class="found">
        <li v-for="file in adoptable" :key="file.path">
          <span class="mono">{{ file.path }}</span>
          <span class="muted">
            {{ bytes(file.sizeBytes || file.size_bytes) }}
            <template v-if="file.last_modified"> &middot; {{ recordedAt(file.last_modified) }}</template>
          </span>
        </li>
      </ul>

      <div class="row" style="margin-top: 1.25rem">
        <button class="btn btn-primary" :disabled="running" @click="apply">
          {{ running ? 'Working…' : `Adopt ${adoptable.length} ${adoptable.length === 1 ? 'file' : 'files'}` }}
        </button>
        <Link class="btn" :href="`/libraries/${library.id}`">Cancel</Link>
      </div>
      <p class="hint" style="margin-top: .75rem">
        Writes one small JSON file per video, then rebuilds the catalog. Your
        videos are not touched, and nothing is ever deleted or overwritten.
      </p>
    </div>

    <!-- SPEC's line throughout: report it, do not hide it. None of these stop
         the sweep; they are things a person should know about. -->
    <div v-if="problems.length" class="card card-pad">
      <h2>Worth a look</h2>
      <ul class="found">
        <li v-for="problem in problems" :key="problem.key">
          <span class="mono">{{ problem.key }}</span>
          <span class="muted">{{ problem.detail }}</span>
        </li>
      </ul>
    </div>
  </template>
</template>

<style scoped>
.found { list-style: none; margin: 0; padding: 0; }
.found li {
  display: flex; justify-content: space-between; gap: 1rem;
  padding: .45rem 0; border-top: 1px solid var(--border); font-size: .88rem;
}
.found li:first-child { border-top: 0; }
.found .muted { white-space: nowrap; font-size: .82rem; }
</style>
