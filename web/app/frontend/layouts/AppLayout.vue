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
      <!-- Whose libraries these are, which stops mattering only while you are
           the sole member. Same pill as the provider badges, so a badge means
           one thing throughout. -->
      <span v-if="user.organizationName" class="pill org">{{ user.organizationName }}</span>
      <span class="muted email">{{ user.emailAddress }}</span>
      <button class="btn btn-sm" @click="signOut">Sign out</button>
    </nav>
  </header>

  <div :class="$attrs.narrow ? 'wrap-narrow' : 'wrap'">
    <div v-if="flash.notice" class="flash flash-notice">{{ flash.notice }}</div>
    <div v-if="flash.alert" class="flash flash-alert">{{ flash.alert }}</div>
    <slot />
  </div>
</template>

<style scoped>
.org { font-size: .78rem; padding: .18rem .55rem; }
.email { font-size: .85rem; }

/* On a phone the header has to hold a brand, a nav link, this and a button.
   The address is the least useful of them -- you know who you signed in as,
   and the organization is the thing that changes as people are invited. */
@media (max-width: 34rem) {
  .email { display: none; }
}
</style>
