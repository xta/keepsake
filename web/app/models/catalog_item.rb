class CatalogItem < ApplicationRecord
  belongs_to :catalog

  scope :newest_first, -> { order(Arel.sql("recorded_at DESC NULLS LAST"), :path) }
  scope :oldest_first, -> { order(Arel.sql("recorded_at ASC NULLS LAST"), :path) }
  scope :by_path, -> { order(:path) }

  # The filename, which is what to show when a sidecar carries no title.
  # SPEC: surface untitled media rather than hiding it.
  def filename = path.to_s.split("/").last

  def display_title = title.presence || filename

  def untitled? = title.blank?

  # Companion keys are the media key plus a suffix, so they are derived, never
  # guessed. `thumbnail` in the sidecar is advisory and may be stale, so it is
  # only trusted for its extension.
  def thumbnail_key
    return nil if thumbnail.blank?
    "#{path.split('/')[0..-2].join('/')}/#{thumbnail}".delete_prefix("/")
  end

  def playable? = Keepsake::Media.playable?(path)
  def kind = Keepsake::Media.kind(path)
end
