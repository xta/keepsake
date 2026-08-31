<script setup>
import { Link, useForm } from '@inertiajs/vue3'
import AppLayout from '../../layouts/AppLayout.vue'
defineOptions({ layout: AppLayout })

const props = defineProps({
  token: String,
  invitedEmail: String,
  unusableReason: String,
})

const form = useForm({
  email_address: props.invitedEmail || '',
  password: '',
  password_confirmation: '',
})
</script>

<template>
  <div style="max-width: 24rem; margin: 2rem auto;">
    <template v-if="unusableReason">
      <h1>This invitation cannot be used</h1>
      <p class="muted" style="margin: .75rem 0 1.5rem;">{{ unusableReason }}</p>
      <Link class="btn" href="/session/new">Back to sign in</Link>
    </template>

    <template v-else>
      <h1>Create your account</h1>
      <p class="muted" style="margin: .5rem 0 1.5rem; font-size: .9rem;">
        You have been invited to keepsake.
      </p>

      <form class="card card-pad" @submit.prevent="form.post(`/invites/${token}`)">
        <div class="field">
          <label for="email">Email address</label>
          <input id="email" v-model="form.email_address" type="email" autocomplete="username" required autofocus />
          <div v-if="form.errors.email_address" class="err">{{ form.errors.email_address }}</div>
        </div>
        <div class="field">
          <label for="password">Password</label>
          <input id="password" v-model="form.password" type="password" autocomplete="new-password" required />
          <div class="hint">At least 8 characters.</div>
          <div v-if="form.errors.password" class="err">{{ form.errors.password }}</div>
        </div>
        <div class="field">
          <label for="confirm">Confirm password</label>
          <input id="confirm" v-model="form.password_confirmation" type="password" autocomplete="new-password" required />
          <div v-if="form.errors.password_confirmation" class="err">{{ form.errors.password_confirmation }}</div>
        </div>
        <button class="btn btn-primary" style="width: 100%" :disabled="form.processing">Create account</button>
      </form>
    </template>
  </div>
</template>
