ourApp.config(['$translateProvider', function ($translateProvider) {
    $translateProvider.useSanitizeValueStrategy(null);
    $translateProvider.translations('en', {
        'TAGLINE': 'File sync for the office or home that is backed by <strong>Subversion</strong> (your own or cloud based), with revision history, permissions, and built for multiple colleagues or family members',
        'FOOTER': '&copy; 2017 <b>Paul Hammant</b>. All Rights Reserved',
        'KNOW_MORE': 'MORE INFO?',
        'FEATURES': 'There are lots of features',
        'LIST': 'Here is a handy list!',
        'FILE_TYPES': 'Large and small file types',
        'ALL_SORTS': 'Spreadsheets, movies, MP3s, pictures, etc',
        'MANY': 'One or thousands of concurrent users',
        'RW_PERMS': 'Fine-grained read and write permissions',
        'GROUPS': 'User groups too!',
        'SVN': 'Using Subversion means many features come by default',
        'HIST': 'Terabytes of revision history is permanently retained',
        'POWER_USERS': 'Power users can use traditional Svn workflows',
        'CLI_TOOLS': 'like checkout, commit and batch operations',
        'STILL_READING': 'Still Reading? Cool, have some more features...',
        'X_PLAT': 'Works on Windows, Mac and Linux',
        'EXCEPT': 'Not for iOS or Android, yet',
        'NO_SVN': 'Subsyncit does not use Subversion at all on the client side',
        'NO_WC': 'That means no &apos;working copy&apos; or .svn folders (or duplicated files)',
        'TESTIMONIALS': 'Testimonials from those using it',
        'TESTIMONIAL_1': 'I love this thing - it is just what I have always wanted',
        'PH': 'Paul Hammant',
        'TESTIMONIAL_2': 'I hope he is going to stop talking about it soon',
        'PH_WIFE': 'Paul&apos;s wife',
        'GH': 'The app is open source on GitHub (of course)'
    });

    $translateProvider.translations('es', {
        'TAGLINE': 'File sync for the office or home that is backed by <strong>Subversion</strong> (your own or cloud based), with revision history, permissions, and built for multiple colleagues or family members',
        'FOOTER': '&copy; 2017 <b>Paul Hammant</b>. All Rights Reserved',
        'KNOW_MORE': 'MORE INFO?',
        'FEATURES': 'There are lots of features',
        'LIST': 'Here is a handy list!',
        'FILE_TYPES': 'Large and small file types',
        'ALL_SORTS': 'Spreadsheets, movies, MP3s, pictures, etc',
        'MANY': 'One or thousands of concurrent users',
        'RW_PERMS': 'Fine-grained read and write permissions',
        'GROUPS': 'User groups too!',
        'SVN': 'Using Subversion means many features come by default',
        'HIST': 'Terabytes of revision history is permanently retained',
        'POWER_USERS': 'Power users can use traditional Svn workflows',
        'CLI_TOOLS': 'like checkout, commit and batch operations',
        'STILL_READING': 'Still Reading? Cool, have some more features...',
        'X_PLAT': 'Works on Windows, Mac and Linux',
        'EXCEPT': 'Not for iOS or Android, yet',
        'NO_SVN': 'Subsyncit does not use Subversion at all on the client side',
        'NO_WC': 'That means no &apos;working copy&apos; or .svn folders (or duplicated files)',
        'TESTIMONIALS': 'Testimonials from those using it',
        'TESTIMONIAL_1': 'I love this thing - it is just what I have always wanted',
        'PH': 'Paul Hammant',
        'TESTIMONIAL_2': 'I hope he is going to stop talking about it soon',
        'PH_WIFE': 'Paul&apos;s wife',
        'GH': 'The app is open source on GitHub (of course)'
    });

    var userLang = navigator.language || navigator.userLanguage;
    var defaultLanguage = userLang.split('-')[0];
    $translateProvider.preferredLanguage(defaultLanguage);
}]);
