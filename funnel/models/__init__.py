"""Provide configuration for models and import all into a common `models` namespace."""

# pyright: reportUnsupportedDunderAll=false

# The second half of this file is dynamically generated. Run `make initpy` to
# regenerate. Since lazy_loader is opaque to static type checkers, there's an overriding
# `__init__.pyi` file that is also autogenerated. Pylint does not process the .pyi file,
# so some tests cause false positives and must be disabled (see `pyproject.toml`)

__protected__ = ['types']

# --- Everything below this line is auto-generated using `make initpy` -----------------

import lazy_loader

__getattr__, __dir__, __all__ = lazy_loader.attach_stub(__name__, __file__)

__all__ = [
    "ACCOUNT_STATE",
    "Account",
    "AccountAndAnchor",
    "AccountEmail",
    "AccountEmailClaim",
    "AccountExternalId",
    "AccountMembership",
    "AccountOldId",
    "AccountPasswordNotification",
    "AccountPhone",
    "Anchor",
    "AuthClient",
    "AuthClientCredential",
    "AuthClientPermissions",
    "AuthClientTeamPermissions",
    "AuthCode",
    "AuthToken",
    "BaseIdNameMixin",
    "BaseMixin",
    "BaseNameMixin",
    "BaseScopedIdMixin",
    "BaseScopedIdNameMixin",
    "BaseScopedNameMixin",
    "Comment",
    "CommentModeratorReport",
    "CommentReplyNotification",
    "CommentReportReceivedNotification",
    "Commentset",
    "CommentsetMembership",
    "ContactExchange",
    "CoordinatesMixin",
    "Draft",
    "DuckTypeAccount",
    "DynamicMapped",
    "EMAIL_DELIVERY_STATE",
    "EmailAddress",
    "EmailAddressBlockedError",
    "EmailAddressError",
    "EmailAddressInUseError",
    "EmailAddressMixin",
    "GeoAdmin1Code",
    "GeoAdmin2Code",
    "GeoAltName",
    "GeoCountryInfo",
    "GeoName",
    "GeonameModel",
    "ImgeeFurl",
    "ImgeeType",
    "IncompleteUserMigrationError",
    "IntTitle",
    "LOGIN_SESSION_VALIDITY_PERIOD",
    "Label",
    "LocaleType",
    "LoginSession",
    "LoginSessionError",
    "LoginSessionExpiredError",
    "LoginSessionInactiveUserError",
    "LoginSessionRevokedError",
    "MODERATOR_REPORT_TYPE",
    "Mailer",
    "MailerDraft",
    "MailerRecipient",
    "MailerState",
    "Mapped",
    "MarkdownCompositeBase",
    "MarkdownCompositeBasic",
    "MarkdownCompositeDocument",
    "MarkdownCompositeInline",
    "MembershipError",
    "MembershipRecordTypeEnum",
    "MembershipRecordTypeError",
    "MembershipRevokedError",
    "Model",
    "ModelBase",
    "ModelIdProtocol",
    "ModelProtocol",
    "ModelRoleProtocol",
    "ModelSearchProtocol",
    "ModelTimestampProtocol",
    "ModelUrlProtocol",
    "ModelUuidProtocol",
    "NewCommentNotification",
    "NoIdMixin",
    "Notification",
    "NotificationFor",
    "NotificationPreferences",
    "NotificationRecipient",
    "NotificationType",
    "OptionalEmailAddressMixin",
    "OptionalPhoneNumberMixin",
    "Organization",
    "OrganizationAdminMembershipNotification",
    "OrganizationAdminMembershipRevokedNotification",
    "PASSWORD_MAX_LENGTH",
    "PASSWORD_MIN_LENGTH",
    "PROPOSAL_STATE",
    "PhoneNumber",
    "PhoneNumberBlockedError",
    "PhoneNumberError",
    "PhoneNumberInUseError",
    "PhoneNumberInvalidError",
    "PhoneNumberMixin",
    "Placeholder",
    "PreviewNotification",
    "Project",
    "ProjectCrewMembershipNotification",
    "ProjectCrewMembershipRevokedNotification",
    "ProjectLocation",
    "ProjectMembership",
    "ProjectRedirect",
    "ProjectRsvpStateEnum",
    "ProjectSponsorMembership",
    "ProjectStartingNotification",
    "ProjectTomorrowNotification",
    "ProjectUpdateNotification",
    "Proposal",
    "ProposalLabelProxy",
    "ProposalLabelProxyWrapper",
    "ProposalMembership",
    "ProposalReceivedNotification",
    "ProposalSponsorMembership",
    "ProposalSubmittedNotification",
    "ProposalSuuidRedirect",
    "Query",
    "QueryProperty",
    "RESERVED_NAMES",
    "RSVP_STATUS",
    "RegistrationCancellationNotification",
    "RegistrationConfirmationNotification",
    "RegistryMixin",
    "ReorderMixin",
    "RoleMixin",
    "Rsvp",
    "RsvpStateEnum",
    "SavedProject",
    "SavedSession",
    "Session",
    "Shortlink",
    "SiteMembership",
    "SmsMessage",
    "SmsStatusEnum",
    "SyncTicket",
    "TSVectorType",
    "Team",
    "TicketClient",
    "TicketEvent",
    "TicketEventParticipant",
    "TicketParticipant",
    "TicketType",
    "TimestampMixin",
    "TimezoneType",
    "Update",
    "UrlType",
    "User",
    "UuidMixin",
    "VISIBILITY_STATE",
    "Venue",
    "VenueRoom",
    "VideoError",
    "VideoMixin",
    "account",
    "account_membership",
    "add_search_trigger",
    "add_to_class",
    "auth_client",
    "auth_client_login_session",
    "backref",
    "base",
    "canonical_phone_number",
    "check_password_strength",
    "comment",
    "commentset_membership",
    "contact_exchange",
    "db",
    "declarative_mixin",
    "declared_attr",
    "deleted_account",
    "draft",
    "email_address",
    "geoname",
    "getextid",
    "getuser",
    "helpers",
    "hybrid_property",
    "label",
    "login_session",
    "mailer",
    "membership_mixin",
    "merge_accounts",
    "moderation",
    "notification",
    "notification_categories",
    "notification_type_registry",
    "notification_types",
    "notification_web_types",
    "parse_phone_number",
    "parse_video_url",
    "phone_blake2b160_hash",
    "phone_number",
    "postgresql",
    "profanity",
    "project",
    "project_child_role_map",
    "project_child_role_set",
    "project_membership",
    "project_venue_primary_table",
    "proposal",
    "proposal_membership",
    "quote_autocomplete_like",
    "quote_autocomplete_tsquery",
    "relationship",
    "removed_account",
    "reorder_mixin",
    "rsvp",
    "sa",
    "sa_exc",
    "sa_orm",
    "saved",
    "session",
    "shortlink",
    "site_membership",
    "sponsor_membership",
    "sync_ticket",
    "types",
    "typing",
    "unknown_account",
    "update",
    "user_signals",
    "utils",
    "valid_account_name",
    "valid_name",
    "validate_phone_number",
    "venue",
    "video_mixin",
    "visual_field_delimiter",
    "with_roles",
]
