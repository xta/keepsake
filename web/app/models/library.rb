# One bucket connection belonging to one user.
#
# Holds credentials, so read `Keepsake::EndpointGuard` before changing anything
# here: every field on this record eventually becomes an outbound request from
# our server to a host the user chose.
class Library < ApplicationRecord
  belongs_to :user
  has_one :catalog, dependent: :destroy

  # The secret is encrypted at rest, non-deterministic: we never query by it,
  # and non-deterministic ciphertext does not leak equality between rows.
  encrypts :secret_access_key

  enum :provider, Keepsake::Provider::NAMES.index_by(&:itself), validate: true
  enum :access_level, { read_only: "read_only", read_write: "read_write" },
       validate: true, prefix: :access

  # Only used when building an r2 endpoint from a form. Never stored -- the
  # derived endpoint is what persists.
  attr_accessor :account_id

  before_validation :sanitize_pasted_values
  before_validation :derive_endpoint
  before_validation :normalize_prefix

  validates :label, presence: true, uniqueness: { scope: :user_id,
            message: "is already used by another of your libraries" }
  validates :bucket, presence: true
  validates :region, presence: true
  validates :endpoint, presence: true
  # Catch a bad region here, on the form, rather than 500ing from inside the
  # AWS SDK on the first request the library ever makes.
  validates :region, format: { with: /\A[a-z0-9][a-z0-9-]*\z/,
            message: "should look like us-west-001, not a full endpoint" },
            allow_blank: true
  validates :access_key_id, presence: true
  validates :secret_access_key, presence: true
  validate  :endpoint_must_be_safe
  validate  :provider_must_be_selectable

  scope :ordered, -> { order(:label) }

  def viewable_by?(other) = user_id == other&.id
  def editable_by?(other) = viewable_by?(other)

  # Never render the secret. This is what the edit form shows instead.
  def secret_hint
    return nil if secret_access_key.blank?
    "#{'•' * 8}#{secret_access_key.to_s.last(4)}"
  end

  def client
    @client ||= Keepsake::Client.for(self)
  end

  def verified? = last_verified_at.present? && last_error.blank?

  private
    # Everything here comes off a clipboard, out of a provider's console. The
    # common mistakes are mechanical -- a trailing slash, an s3:// scheme, a
    # newline picked up with a key -- and each one otherwise surfaces as a
    # signature failure or a 500 from inside the SDK, a long way from the field
    # that caused it.
    def sanitize_pasted_values
      # A key with a stray space signs incorrectly and reports only
      # "SignatureDoesNotMatch", which sends people hunting for the wrong bug.
      self.access_key_id = access_key_id.to_s.strip.presence
      self.secret_access_key = secret_access_key.to_s.strip.presence if secret_access_key.present?

      self.label = label.to_s.strip.presence

      # Accept "s3://bucket", "bucket/", or the bucket's console URL.
      unless provider == "local"
        self.bucket = bucket.to_s.strip
          .sub(%r{\As3://}i, "")
          .sub(%r{\Ahttps?://}i, "")
          .split("/").first.to_s.presence
      else
        self.bucket = bucket.to_s.strip.presence
      end

      self.region = Keepsake::Provider.normalize_region(region).presence

      if endpoint.present?
        cleaned = endpoint.to_s.strip.chomp("/")
        # A bare host is the usual paste. Assume https rather than rejecting
        # it, since https is the only scheme this app will accept anyway.
        cleaned = "https://#{cleaned}" unless cleaned.match?(%r{\A[a-z][a-z0-9+.-]*://}i)
        self.endpoint = cleaned
      end
    end

    def derive_endpoint
      if provider == "local"
        # A directory, not a URL. Record it plainly so the column is populated
        # and nothing downstream mistakes it for something to connect to.
        self.endpoint = "local:#{bucket}"
        self.region = "local"
        return
      end

      derived = Keepsake::Provider.endpoint_for(
        provider, region: region, account_id: account_id, endpoint: endpoint
      )
      self.endpoint = derived if derived.present?
      self.region = Keepsake::Provider.region_for(provider, region: region, endpoint: endpoint)
    end

    def normalize_prefix
      # Store prefixes in one shape: no leading slash, exactly one trailing
      # slash, blank when empty. Otherwise "media", "media/" and "/media"
      # produce three different key layouts from the same intent.
      self.prefix = prefix.to_s.strip.delete_prefix("/").presence
      self.prefix = "#{prefix.chomp('/')}/" if prefix.present?
    end

    def provider_must_be_selectable
      return if provider.blank?
      unless Keepsake::Provider.selectable.include?(provider)
        errors.add(:provider, "is not available in this environment")
      end
    end

    def endpoint_must_be_safe
      return if endpoint.blank?
      # A local directory is not a URL and never leaves this machine.
      return if provider == "local"
      Keepsake::EndpointGuard.validate!(endpoint)
    rescue Keepsake::EndpointGuard::Rejected => e
      errors.add(:endpoint, e.message)
    end
end
