class Invite < ApplicationRecord
  DEFAULT_TTL = 14.days

  # Nullable: the very first invite on a fresh install has no creator, because
  # there is nobody yet. Inventing a placeholder user to satisfy a foreign key
  # would be a lie in the audit trail.
  belongs_to :created_by, class_name: "User", optional: true
  belongs_to :claimed_by, class_name: "User", optional: true

  has_secure_token :token, length: 32

  # Advisory only. An invite may name the address it was meant for, but
  # claiming does not require matching it -- pinning the address means a typo
  # burns the invite and someone has to mint another.
  normalizes :email_address, with: ->(e) { e&.strip&.downcase.presence }

  before_validation :set_default_expiry, on: :create
  validates :expires_at, presence: true

  scope :claimed, -> { where.not(claimed_at: nil) }
  scope :unclaimed, -> { where(claimed_at: nil) }

  def claimed? = claimed_at.present?
  def expired? = expires_at.past?
  def usable? = !claimed? && !expired?

  # Why an invite cannot be used, phrased for a person staring at a dead link.
  def unusable_reason
    return nil if usable?
    return "This invitation has already been used." if claimed?
    "This invitation expired on #{expires_at.to_date.to_fs(:long)}."
  end

  def claim!(user)
    update!(claimed_by: user, claimed_at: Time.current)
  end

  private
    def set_default_expiry
      self.expires_at ||= DEFAULT_TTL.from_now
    end
end
