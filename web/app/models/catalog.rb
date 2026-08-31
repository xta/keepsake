# A parsed copy of one bucket's index.json.
#
# CACHE, NEVER SOURCE OF TRUTH. SPEC.md: "No external datastore. Nothing
# outside the bucket may be required to read or interpret its contents."
# Dropping this table and refetching loses nothing. It exists so the grid can
# sort and paginate without re-parsing a whole catalog inside a request.
class Catalog < ApplicationRecord
  belongs_to :library
  has_many :items, class_name: "CatalogItem", dependent: :delete_all

  # How long a fetched catalog is served before we ask the bucket again.
  # A stale catalog is a cosmetic bug per SPEC, not data loss.
  TTL = 15.minutes

  def stale? = fetched_at.nil? || fetched_at < TTL.ago
end
