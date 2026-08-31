module Keepsake
  # One error type for every storage failure, carrying a message fit to show a
  # person on the library's settings page. SPEC's spirit throughout is "report
  # it, do not hide it" -- so nothing here swallows a failure silently.
  class StorageError < StandardError
    attr_reader :cause_class

    def initialize(message, cause_class: nil)
      super(message)
      @cause_class = cause_class
    end
  end
end
