<script setup>
import { Link, useForm } from '@inertiajs/vue3'
import AppLayout from '../../layouts/AppLayout.vue'
defineOptions({ layout: AppLayout })

const form = useForm({ email_address: '' })
</script>

<template>
  <div style="max-width: 24rem; margin: 2rem auto;">
    <h1>Reset your password</h1>
    <p class="muted" style="margin: .5rem 0 1.5rem; font-size: .9rem;">
      We will email a reset link if an account exists for that address.
    </p>
    <form class="card card-pad" @submit.prevent="form.post('/passwords')">
      <div class="field">
        <label for="email">Email address</label>
        <input id="email" v-model="form.email_address" type="email" required autofocus />
      </div>
      <button class="btn btn-primary" style="width: 100%" :disabled="form.processing">Send reset link</button>
    </form>
    <p class="muted" style="margin-top: 1rem; font-size: .85rem; text-align: center;">
      <Link href="/session/new">Back to sign in</Link>
    </p>
  </div>
</template>
