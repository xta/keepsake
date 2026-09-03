class User < ApplicationRecord
  has_secure_password
  has_many :sessions, dependent: :destroy

  # Libraries belong to the organization, not to whoever added them, so this is
  # the trail of who added what rather than a claim of ownership.
  belongs_to :organization
  # Everything this person can reach, which is the organization's rather than
  # theirs. Named for what it means to them, not for who holds the key.
  has_many :libraries, through: :organization
  has_many :added_libraries, class_name: "Library", foreign_key: :created_by_id,
           dependent: :nullify, inverse_of: :created_by

  # Who let this person in. Kept because an invite-only app is only as
  # accountable as its trail.
  belongs_to :invited_by, class_name: "User", optional: true
  has_many :sent_invites, class_name: "Invite", foreign_key: :created_by_id,
           dependent: :nullify, inverse_of: :created_by

  normalizes :email_address, with: ->(e) { e.strip.downcase }

  validates :email_address, presence: true,
            format: { with: URI::MailTo::EMAIL_REGEXP, message: "is not a valid address" }
  # has_secure_password already requires a password on create; this only adds
  # a floor, and allow_nil keeps it out of the way when updating other fields.
  validates :password, length: { minimum: 8 }, allow_nil: true
end
