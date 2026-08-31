<script setup>
import { Link, usePage, router } from '@inertiajs/vue3'
import { computed } from 'vue'

const page = usePage()
const user = computed(() => page.props.currentUser)
const flash = computed(() => page.props.flash || {})

function signOut() {
  router.delete('/session')
}
</script>

<template>
  <header class="app-header">
    <Link class="brand" :href="user ? '/libraries' : '/session/new'">
      keepsake
    </Link>
    <Link v-if="user" href="/libraries" class="nav-link">Libraries</Link>

    <nav v-if="user">
      <span class="muted" style="font-size: .85rem">{{ user.emailAddress }}</span>
      <button class="btn btn-sm" @click="signOut">Sign out</button>
    </nav>
  </header>

  <div :class="$attrs.narrow ? 'wrap-narrow' : 'wrap'">
    <div v-if="flash.notice" class="flash flash-notice">{{ flash.notice }}</div>
    <div v-if="flash.alert" class="flash flash-alert">{{ flash.alert }}</div>
    <slot />
  </div>
</template>
