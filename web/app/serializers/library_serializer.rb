# Explicit allowlist of what reaches the browser.
#
# The point is `secret_access_key`. Trusting `as_json` or `to_json` means one
# added column can quietly ship a credential to the client, so every field a
# page can see is named here by hand.
module LibrarySerializer
  module_function

  def call(library)
    {
      id: library.id,
      label: library.label,
      provider: library.provider,
      providerLabel: Keepsake::Provider.form_metadata.dig(library.provider, :label),
      endpoint: library.endpoint,
      region: library.region,
      bucket: library.bucket,
      prefix: library.prefix,
      forcePathStyle: library.force_path_style,
      accessLevel: library.access_level,
      # Drives whether write features are shown at all. A read-only library
      # should not be offered a button it cannot use.
      writable: library.access_read_write?,
      accessKeyId: library.access_key_id,
      # Never the secret itself -- only enough to recognise which key is stored.
      secretHint: library.secret_hint,
      sweepState: library.sweep_state,
      sweepMessage: library.sweep_message,
      sweeping: library.sweeping?,
      lastVerifiedAt: library.last_verified_at&.iso8601,
      lastError: library.last_error,
      verified: library.verified?
    }
  end

  def summary(library, catalog)
    call(library).merge(
      itemCount: catalog&.item_count,
      totalBytes: catalog&.total_bytes,
      generatedAt: catalog&.generated_at&.iso8601,
      fetchedAt: catalog&.fetched_at&.iso8601
    )
  end
end
