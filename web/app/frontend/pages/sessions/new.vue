<script setup>
import { Head, useForm } from '@inertiajs/vue3'
import AppLayout from '../../layouts/AppLayout.vue'
defineOptions({ layout: AppLayout })

const form = useForm({ email_address: '', password: '' })
</script>

<template>
  <Head title="Sign in" />
  <div style="max-width: 24rem; margin: 2rem auto;">
    <h1>Sign in</h1>

    <form class="card card-pad" @submit.prevent="form.post('/session')">
      <div class="field">
        <label for="email">Email address</label>
        <input id="email" v-model="form.email_address" type="email" autocomplete="username" required autofocus />
      </div>
      <div class="field">
        <label for="password">Password</label>
        <input id="password" v-model="form.password" type="password" autocomplete="current-password" required />
      </div>
      <button class="btn btn-primary" style="width: 100%" :disabled="form.processing">Sign in</button>
    </form>

    <p class="muted" style="margin-top: 1rem; font-size: .85rem; text-align: center;">
      Lost your password? Ask whoever runs this install.
    </p>
  </div>
</template>
