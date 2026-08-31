module CatalogItemSerializer
  module_function

  # `client` is used only to sign URLs, which is local HMAC and costs no
  # network call -- so a 200-thumbnail page is no more expensive than an empty
  # one. URLs are generated at render time so they expire from the moment the
  # page is seen, not from whenever a cache was warmed.
  def call(item, client:, media: false)
    props = {
      id: item.id,
      path: item.path,
      filename: item.filename,
      title: item.title,
      displayTitle: item.display_title,
      untitled: item.untitled?,
      recordedAt: item.recorded_at,
      uploadedAt: item.uploaded_at&.iso8601,
      durationS: item.duration_s,
      sizeBytes: item.size_bytes,
      mediaType: item.media_type,
      kind: item.kind,
      playable: item.playable?,
      formatLabel: Keepsake::Media.format_label(item.path),
      thumbnailUrl: thumbnail_url(item, client)
    }

    if media
      props[:mediaUrl] = item.playable? ? client.presigned_url(item.path) : nil
      props[:downloadUrl] = client.download_url(item.path)
      # The whole sidecar, so the detail page can show fields this app has
      # never heard of. SPEC requires unknown fields to survive; hiding them
      # from the one page that could display them would be a poor reading.
      props[:sidecar] = item.sidecar
    end

    props
  end

  def thumbnail_url(item, client)
    key = item.thumbnail_key
    return nil if key.blank?
    client.presigned_url(key, expires_in: Keepsake::S3Client::THUMBNAIL_EXPIRY)
  end
end
